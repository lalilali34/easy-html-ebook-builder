#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inbox_ingest.py — 纯文本自动入库
================================

把 `inbox/` 下的 .txt 丢进来，自动：
  1. 读第一行当标题
  2. 生成 slug（英文优先 -> 拼音 -> 标题哈希兜底）
  3. 拼当前日期得到 article_id：`YYYYMMDD_slug`
  4. 建好 corpus/<id>/{source,analysis,text}/ 目录层级
  5. 原文转成 `source/raw.md`（首行变 `# 标题`）
  6. 处理完的 txt 归档到 _archive/consumed/（不删除）

零第三方依赖。装了 pypinyin 会自动产出语义化拼音 slug，没装则退化为
`article-<sha1前6位>`，同标题结果稳定。

用法：
    python upstream/src/inbox_ingest.py                 # 扫 inbox/ 全部
    python upstream/src/inbox_ingest.py --file inbox/x.txt
    python upstream/src/inbox_ingest.py --dry-run
    python upstream/src/inbox_ingest.py --slug my-slug --date 20261110
    python upstream/src/inbox_ingest.py --keep          # 不归档原 txt
    python upstream/src/inbox_ingest.py --force         # 覆盖已存在的包

退出码：
    0  成功（含"inbox 为空"）
    3  源文件无效
    5  读取失败
"""

import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "corpus"
INBOX = ROOT / "inbox"
ARCHIVE = ROOT / "_archive" / "consumed"

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def log(msg):
    print(msg, flush=True)


def fail(msg):
    print("[FAIL] " + str(msg), file=sys.stderr, flush=True)


# ---------------------------------------------------------------- 文本读取

def read_any_text(path):
    """编码自适应读取，返回 (text, encoding)。"""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "utf-16"):
        try:
            return raw.decode(enc), enc
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8(replace)"


def split_frontmatter(text):
    """
    剥离 YAML frontmatter。返回 (frontmatter_body_or_None, 剩余正文)。
    - 有闭合 `--- ... ---`：剥离元数据块
    - 只有开头一个 `---` 没有闭合：视为误写的分隔线，直接丢弃该行
    """
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for j in range(1, min(len(lines), 200)):
            if lines[j].strip() in ("---", "..."):
                return "\n".join(lines[1:j]), "\n".join(lines[j + 1:])
        return None, "\n".join(lines[1:])
    return None, text


def is_separator(s):
    """判断是否 Markdown 分隔线（--- / *** / ___）。"""
    return bool(s) and set(s) <= set("-*_ ") and len(set(s)) <= 2


# 行首时间码：00:02 / 00:02:15 / [00:02] / 00:02,500
_TM_LINE = re.compile(
    r"(?m)^\s*(?:\[\s*\d{1,2}:\d{2}(?::\d{2})?(?:[,.]\d{1,3})?\s*\]"
    r"|\d{1,2}:\d{2}(?::\d{2})?(?:[,.]\d{1,3})?)\s+"
)


def strip_subtitle_timestamps(text, para_chars=150):
    """
    识别字幕稿（大部分行以时间码开头）并剥离时间码。

    - 剥离后按句末标点 / 累计 150 字合并成段落，避免"每行一段"太碎。
    - 返回 (清理后文本, 是否处理过)。
    """
    lines = text.splitlines()
    if not lines:
        return text, False

    hit = sum(1 for ln in lines if _TM_LINE.match(ln))
    if hit < 3 or hit < len(lines) * 0.3:
        return text, False

    cleaned = []
    for ln in lines:
        s = _TM_LINE.sub("", ln).strip()
        if s:
            cleaned.append(s)

    paras, buf = [], ""
    for s in cleaned:
        buf += s
        if len(buf) >= para_chars or s.endswith(("。", "！", "？", "…")):
            paras.append(buf)
            buf = ""
    if buf:
        paras.append(buf)

    return "\n\n".join(paras), True


def extract_title(text, fallback=""):
    """
    标题优先级：
      1. `# 标题`
      2. 首个非空、非分隔线且长度 <= 60 的行
      3. fallback（通常是文件名）
    避免把一整段正文误当成标题。
    """
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()

    for line in text.splitlines():
        s = line.strip()
        if not s or is_separator(s):
            continue
        if len(s) <= 60:
            return s
        break

    return fallback or ""


# ---------------------------------------------------------------- slug

def clean_slug(s, maxlen=48):
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s[:maxlen].strip("-")


def slug_from_title(title):
    """
    返回 (slug, 来源标签)。
    1) 英文/数字词 -> 直接连字符拼接
    2) 纯中文 -> pypinyin（若已安装）
    3) 仍不行 -> article-<sha1(title)[:6]>，同标题稳定
    """
    words = re.findall(r"[A-Za-z][A-Za-z0-9]*", title)
    if words:
        slug = clean_slug("-".join(words[:8]))
        if slug:
            return slug, "english"

    try:
        from pypinyin import lazy_pinyin  # type: ignore
        parts = [clean_slug(x) for x in lazy_pinyin(title)]
        slug = clean_slug("-".join(p for p in parts if p))
        if slug:
            return slug, "pinyin"
    except Exception:
        pass

    h = hashlib.sha1(title.encode("utf-8")).hexdigest()[:6]
    return "article-" + h, "hash"


# ---------------------------------------------------------------- 转换

def to_markdown(text, title):
    """首行标题转 `# 标题`，正文保留；避免标题重复出现。"""
    lines = text.splitlines()
    out = []
    dropped_title = False
    for line in lines:
        s = line.strip()
        if not dropped_title and s and s.lstrip("#").strip() == title:
            dropped_title = True
            continue
        out.append(line)
    body = "\n".join(out).strip("\n")
    return "# " + title + "\n\n" + body + "\n"


def ingest_file(path, slug_override=None, date_str=None,
                dry_run=False, keep=False, force=False):
    """返回 (article_id, error)。"""
    try:
        text, enc = read_any_text(path)
    except OSError as e:
        return None, "读取失败: %s" % e

    if not text.strip():
        return None, "文件为空"

    frontmatter, text = split_frontmatter(text)
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    text, was_sub = strip_subtitle_timestamps(text)
    if was_sub:
        log("[meta  ] 检测到字幕时间码，已剥离并按段合并")
    # 字幕稿：标题取剥离前的第一行（去时间码），避免首段过长导致 fallback
    title_hint = _TM_LINE.sub("", first_line).strip() if was_sub else ""
    title = extract_title(text, fallback=title_hint or path.stem)
    if not title:
        return None, "找不到标题行"

    if slug_override:
        slug = clean_slug(slug_override)
        origin = "manual"
        if not slug:
            return None, "--slug 不合法（只允许 a-z0-9-）"
    else:
        slug, origin = slug_from_title(title)

    d = date_str or date.today().strftime("%Y%m%d")
    if not re.match(r"^[0-9]{8}$", d):
        return None, "--date 必须是 YYYYMMDD"

    article_id = "%s_%s" % (d, slug)
    pkg = CORPUS / article_id

    log("[title] %s" % title)
    log("[slug ] %s（来源：%s）" % (slug, origin))
    log("[id   ] %s" % article_id)
    log("[enc  ] %s" % enc)

    if pkg.exists() and not force:
        return None, "文章包已存在：%s（加 --force 覆盖）" % article_id

    if dry_run:
        log("[dry-run] 将创建 %s" % pkg)
        for sub in ("source", "analysis", "text"):
            log("          %s/%s/" % (article_id, sub))
        log("          source/raw.md（%d 字符）" % len(text))
        return article_id, None

    for sub in ("source", "analysis", "text"):
        (pkg / sub).mkdir(parents=True, exist_ok=True)

    md = to_markdown(text, title)
    raw_md = pkg / "source" / "raw.md"
    with open(str(raw_md), "w", encoding="utf-8", newline="\n") as f:
        f.write(md)

    # 入库元信息：下游据此决定是否跑 pass0 ASR 纠错
    try:
        with open(str(pkg / "source" / "ingest.json"), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({
                "is_subtitle": bool(was_sub),
                "encoding": enc,
                "source_file": path.name,
                "title": title,
            }, ensure_ascii=False, indent=2))
            f.write("\n")
        log("[meta  ] 入库标记：is_subtitle=%s（决定是否跑 pass0 纠错）" % bool(was_sub))
    except Exception as e:
        log("[warn] 写入 ingest.json 失败：%s" % e)

    if frontmatter:
        fm_path = pkg / "source" / "frontmatter.txt"
        with open(str(fm_path), "w", encoding="utf-8", newline="\n") as f:
            f.write(frontmatter.strip() + "\n")
        log("[meta  ] frontmatter 已剥离 -> source/frontmatter.txt")

    # 原始 txt 一并留档
    src_copy = pkg / "source" / ("orig" + path.suffix.lower())
    shutil.copy2(str(path), str(src_copy))

    if not keep:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest_dir = ARCHIVE / stamp
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(dest_dir / path.name))
        log("[archive] %s -> %s" % (path.name, dest_dir / path.name))

    log("[ok] 已入库 %s（%d 字符，%d 行）"
        % (article_id, len(md), len(md.splitlines())))
    log("     下一步：python upstream/src/full_auto.py --file %s" % pkg.name)
    return article_id, None


# ---------------------------------------------------------------- 入口

def main(argv=None):
    ap = argparse.ArgumentParser(description="inbox 纯文本自动入库")
    ap.add_argument("--file", help="只处理指定 txt（默认扫 inbox/）")
    ap.add_argument("--slug", help="手动指定 slug（覆盖自动生成）")
    ap.add_argument("--date", help="覆盖日期 YYYYMMDD（默认今天）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep", action="store_true", help="不归档原 txt")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的文章包")
    args = ap.parse_args(argv)

    INBOX.mkdir(parents=True, exist_ok=True)

    if args.file:
        p = Path(args.file)
        # 相对路径：先按当前目录找，找不到再回退到仓库根（支持从任意目录执行）
        if not p.is_absolute() and not p.is_file():
            cand = ROOT / p
            if cand.is_file():
                p = cand
        targets = [p]
    else:
        targets = sorted(
            q for q in INBOX.iterdir()
            if q.is_file() and q.suffix.lower() in (".txt", ".md")
        )
        if not targets:
            log("[info] inbox/ 里没有 .txt（目录：%s）" % INBOX)
            return 0

    rc = 0
    created = []
    for p in targets:
        if not p.is_file():
            fail("文件不存在: %s" % p)
            rc = 3
            continue
        aid, err = ingest_file(p, args.slug, args.date,
                               args.dry_run, args.keep, args.force)
        if err:
            fail("%s: %s" % (p.name, err))
            rc = 3
            continue
        created.append(aid)

    if created:
        log("\n[summary] 本次入库 %d 篇：%s" % (len(created), ", ".join(created)))
    return rc


if __name__ == "__main__":
    sys.exit(main())
