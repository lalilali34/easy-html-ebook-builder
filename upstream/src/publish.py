#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
publish.py — 交付清单生成器（deliver.json）
===========================================

扫描 corpus/<id>/ 与 terms/<id>.md，生成 corpus/<id>/deliver.json。

**原子写约定**：先写 deliver.json.tmp，再 os.replace() 改名。
下游 render.py 只认 status == "ready" 的 deliver.json，
因此下游永远不会读到写了一半的交付清单。

用法：
    python upstream/src/publish.py --id 20261109_bourgeois
    python upstream/src/publish.py --id 20261109_bourgeois --verify
    python upstream/src/publish.py --id 20261109_bourgeois --title "自定义标题"

退出码：
    0  成功
    1  未捕获异常
    3  必需产物缺失
    4  契约校验未通过（不写 deliver.json，或 --verify 时报告不一致）
    5  读取/解析失败
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

# 复用同目录的 validate.py（严格 schema + 语义校验，零第三方依赖）
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
try:
    import validate as _validate
except ImportError as _err:  # pragma: no cover
    raise SystemExit("[FAIL] 无法导入 upstream/src/validate.py: %s" % _err)

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "corpus"
TERMS_DIR = ROOT / "terms"
CONTRACT = ROOT / "contract"

# --auto-render 要触发的下游脚本
RENDER_PY = ROOT / "downstream" / "src" / "render.py"
INDEX_PY = ROOT / "downstream" / "src" / "build_index.py"

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def log(msg):
    print(msg, flush=True)


def die(code, msg):
    print("[FAIL] " + str(msg), file=sys.stderr, flush=True)
    sys.exit(code)


def read_text(path):
    with open(str(path), "r", encoding="utf-8-sig", errors="strict") as f:
        return f.read().replace("\r\n", "\n")


def write_text(path, text):
    with open(str(path), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def load_json(path):
    return json.loads(read_text(path))


def sha256_file(path):
    h = hashlib.sha256()
    with open(str(path), "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_enums():
    p = CONTRACT / "enums.json"
    if not p.is_file():
        die(5, "缺少契约文件: %s" % p)
    return load_json(p)


def count_term_rows(text):
    """数 terms md 里有效词条行。"""
    n = 0
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 8:
            continue
        if cells[0] and set(cells[0]) <= set("-: "):
            continue
        if "词条名" in cells[1]:
            continue
        if cells[1]:
            n += 1
    return n


def run_downstream(article_id):
    """
    串行触发下游：render（渲染）→ build_index（书架）。
    返回合并退出码（各步取最大值，0 表示全绿）。

    为什么用 import 而不是 subprocess：
    打包成 exe 后 sys.executable 指向启动器自身，`subprocess.run([sys.executable, …])`
    会把 publish 的参数误传给启动器。进程内直接调用各脚本的入口函数才可靠。
    """
    src = str(ROOT / "downstream" / "src")
    if src not in sys.path:
        sys.path.insert(0, src)

    worst = 0

    for name, mod_name in (("render", "render"), ("build_index", "build_index")):
        try:
            log("[auto-render] %s …" % name)
            if mod_name == "render":
                import render as _mod
                rc = _mod.render_one(article_id)
            else:
                import build_index as _mod
                rc = _mod.build(False)
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
            log("[auto-render] %s 退出码 %d" % (name, code))
            worst = max(worst, code)
            continue
        except Exception as e:
            log("[auto-render] %s 失败：%s" % (name, e))
            worst = max(worst, 1)
            continue

        if rc:
            log("[auto-render] %s 退出码 %d" % (name, rc))
            worst = max(worst, rc)
        else:
            log("[auto-render] %s 完成" % name)

    return worst


def build(article_id, title_override=None, verify=False, auto_render=False):
    pkg = CORPUS / article_id
    if not pkg.is_dir():
        die(3, "文章包不存在: %s" % pkg)

    deliver_path = pkg / "deliver.json"
    enums = load_enums()

    # ---------- 收集产物
    candidates = [
        ("analysis", pkg / "analysis" / "analysis.json"),
        ("article", pkg / "text" / "article.md"),
        ("article_examples", pkg / "text" / "article_with_examples.md"),
        ("terms", TERMS_DIR / ("%s.md" % article_id)),
        # 费曼骨架：可选产物，老文章没有就不声明（下游不校验、不报错）
        ("feynman", pkg / "analysis" / "feynman.json"),
    ]
    artifacts = []
    paths = {}
    for kind, p in candidates:
        if not p.is_file():
            if kind != "feynman":
                log("[warn] 缺少产物 %s: %s" % (kind, p))
            continue
        paths[kind] = p
        entry = {
            "kind": kind,
            "path": str(p.relative_to(ROOT)).replace("\\", "/"),
            "sha256": sha256_file(p),
            "bytes": p.stat().st_size,
        }
        if kind == "terms":
            entry["entry_count"] = count_term_rows(read_text(p))
        if kind == "analysis":
            entry["schema"] = "contract/analysis.schema.json"
        artifacts.append(entry)

    if "analysis" not in paths:
        die(3, "%s: 缺 analysis/analysis.json，不能发布" % article_id)
    if "article" not in paths and "article_examples" not in paths:
        die(3, "%s: 缺 article.md / article_with_examples.md，不能发布" % article_id)

    # ---------- 统计
    try:
        analysis = load_json(paths["analysis"])
    except Exception as e:
        die(5, "%s: analysis.json 解析失败: %s" % (article_id, e))

    sk = analysis.get("skeleton") or {}
    blocks = analysis.get("blocks") or []
    recap = analysis.get("recap") or {}
    stats = {
        "skeleton_blocks": len(sk.get("blocks") or []),
        "subblocks": len(blocks),
        "relations": len(analysis.get("relations") or []),
        "three_questions": len(recap.get("three_questions") or []),
        "chapters": len((analysis.get("meta") or {}).get("chapters") or []),
    }

    # ---------- 校验闸门
    checks = {}
    try:
        ok, errs, warns = _validate.validate_analysis(
            analysis, enums, expected_article_id=article_id)
    except SystemExit as e:
        die(5, str(e))
    checks["analysis_schema"] = "pass" if ok else "fail"
    for w in warns:
        log("[schema-warn] " + w)
    for e in errs[:20]:
        log("[schema] " + e)
    if len(errs) > 20:
        log("[schema] … 另有 %d 条错误未显示" % (len(errs) - 20))

    checks["artifact_integrity"] = "pass" if artifacts else "fail"

    if "terms" in paths:
        n = count_term_rows(read_text(paths["terms"]))
        checks["terms_file"] = "pass" if n > 0 else "fail"
        # 术语与正文的最粗校验：至少有一个词条出现在正文里
        article_text = ""
        if "article_examples" in paths:
            article_text = read_text(paths["article_examples"])
        elif "article" in paths:
            article_text = read_text(paths["article"])
        any_hit = False
        for line in read_text(paths["terms"]).splitlines():
            s = line.strip()
            if not s.startswith("|"):
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            if len(cells) < 8 or "词条名" in cells[1]:
                continue
            if cells[1] and cells[1] in article_text:
                any_hit = True
                break
        checks["terms_vs_article"] = "pass" if any_hit else "fail"
        # 解释文字字数已放宽：pass8 不再限制 80–150 字，这里不做长度检查
    else:
        checks["terms_file"] = "skip"
        checks["terms_vs_article"] = "skip"

    # ---------- --verify：只比对，不写
    if verify:
        if not deliver_path.is_file():
            die(4, "%s: deliver.json 不存在" % article_id)
        old = load_json(deliver_path)
        old_map = dict((a["kind"], a) for a in (old.get("artifacts") or []))
        new_map = dict((a["kind"], a) for a in artifacts)
        problems = []
        for kind in sorted(set(old_map) | set(new_map)):
            o = old_map.get(kind)
            n = new_map.get(kind)
            if o is None:
                problems.append("deliver 缺少: %s" % kind)
            elif n is None:
                problems.append("deliver 多出（文件已不存在）: %s" % kind)
            elif o.get("sha256") != n.get("sha256"):
                problems.append("%s 哈希不一致\n  清单 %s\n  实际 %s"
                                % (kind, o.get("sha256"), n.get("sha256")))
        if problems:
            for p in problems:
                log("[mismatch] " + p)
            return 4
        log("[ok] %s: deliver.json 与实际产物一致（%d 个）" % (article_id, len(artifacts)))
        return 0

    # ---------- 组装 deliver.json
    title = title_override
    if not title:
        # 优先成文首行标题（# ...），它才是"书名"；analysis.meta.title 常只是核心问题
        text_p = paths.get("article_examples") or paths.get("article")
        if text_p:
            for line in read_text(text_p).splitlines():
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
    if not title:
        title = (analysis.get("meta") or {}).get("title")
    if not title:
        title = article_id

    deliver = {
        "schema_version": "1.0",
        "article_id": article_id,
        "status": "ready",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "producer": {
            "name": "subtitle-to-structure",
            "version": "0.4.0",
            "pipeline": "upstream/src/publish.py",
        },
        "title": title,
        "artifacts": artifacts,
        "stats": stats,
        "checks": checks,
    }

    tmp = pkg / "deliver.json.tmp"
    write_text(tmp, json.dumps(deliver, ensure_ascii=False, indent=2))
    os.replace(str(tmp), str(deliver_path))

    bad = dict((k, v) for k, v in checks.items() if v == "fail")
    log("[ok] %s -> %s" % (article_id, deliver_path))
    log("     artifacts=%d  stats=%s  checks=%s"
        % (len(artifacts), stats, checks))
    if bad:
        log("[warn] 存在 fail 项，下游 render.py 会拒绝渲染: %s" % bad)
        rc = 4
    else:
        rc = 0

    if auto_render:
        log("[auto-render] deliver.json 已落盘，开始触发下游")
        rc = max(rc, run_downstream(article_id))

    return rc


def main(argv=None):
    ap = argparse.ArgumentParser(description="交付清单生成器")
    ap.add_argument("--id", required=True, help="文章 id")
    ap.add_argument("--title", help="覆盖标题（默认取 analysis.meta.title 或首行 # 标题）")
    ap.add_argument("--verify", action="store_true", help="只校验 deliver.json 与产物是否一致")
    ap.add_argument("--auto-render", action="store_true",
                    help="生成 deliver.json 后自动调用下游 render.py 与 build_index.py")
    args = ap.parse_args(argv)
    try:
        return build(args.id, args.title, args.verify, args.auto_render)
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
