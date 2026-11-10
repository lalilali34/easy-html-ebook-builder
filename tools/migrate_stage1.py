#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
migrate_stage1.py — 一次性迁移工具（旧结构 -> ebook-pipeline 架构）
==================================================================

把 D:\\DSH_workplace\\电子书项目 里现有的《资产阶级法权》全链路数据，
搬进 ebook-pipeline 的统一目录结构，并按篇拆分 terms.md。

本脚本**只跑一次**。迁移完成后可删除，或归档到 _archive/。

用法：
    python tools/migrate_stage1.py --dry-run      # 只看会做什么
    python tools/migrate_stage1.py

约定：
    20261109_bourgeois         <- terms.md 第 28–50 条
    20261026_literary_theory   <- terms.md 第 1–27 条
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(r"D:\DSH_workplace\电子书项目")

BOURGEOIS = "20261109_bourgeois"
LITERARY = "20261026_literary_theory"

TERMS_HEADER = ("| 编号 | 词条名 | 别名/匹配形式 | 类型(1-5) | 解释文字 "
                "| 链接 | 匹配范围 | 排除/备注 |")
TERMS_SEP = "| --- | --- | --- | --- | --- | --- | --- | --- |"

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def log(msg):
    print(msg, flush=True)


def read_text(path):
    with open(str(path), "r", encoding="utf-8-sig", errors="strict") as f:
        return f.read().replace("\r\n", "\n")


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def parse_terms_table(text):
    """返回 [(编号, cells8), ...]，编号为原文编号字符串。"""
    rows = []
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 8:
            continue
        if set(cells[0]) <= set("-: "):
            continue
        if "词条名" in cells[1]:
            continue
        rows.append((cells[0], cells[:8]))
    return rows


def render_terms(rows):
    out = [TERMS_HEADER, TERMS_SEP]
    for _no, cells in rows:
        _no, name, alias, tid, desc, link, scope, note = cells
        # 作用域统一改为"本篇所有出现"（按篇隔离后语义才准确）
        scope = "本篇所有出现"
        out.append("| | %s | %s | %s | %s | %s | %s | %s |"
                   % (name, alias, tid, desc, link, scope, note))
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="旧结构 -> ebook-pipeline 一次性迁移")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if not SRC.is_dir():
        log("[FAIL] 源目录不存在: %s" % SRC)
        return 3

    src_article = SRC / "articles" / "article.md"
    src_examples = SRC / "articles" / "article_with_examples.md"
    src_analysis = SRC / "structure" / "资产阶级法权2" / "analysis.json"
    src_terms = SRC / "terms.md"
    src_fonts = SRC / "fonts"

    plan = []

    pkg = ROOT / "corpus" / BOURGEOIS
    plan.append((src_article, pkg / "text" / "article.md"))
    plan.append((src_examples, pkg / "text" / "article_with_examples.md"))
    plan.append((src_analysis, pkg / "analysis" / "analysis.json"))

    for p in (pkg / "source", pkg / "build"):
        plan.append((None, p))   # 建空目录占位

    for f in sorted(src_fonts.glob("*.woff2")):
        plan.append((f, ROOT / "downstream" / "assets" / "fonts" / f.name))

    log("=== 计划 ===")
    for s, d in plan:
        if s is None:
            log("  mkdir  %s" % d)
        else:
            log("  copy   %s\n      -> %s" % (s, d))

    if args.dry_run:
        log("\n[dry-run] 未执行任何写入。")
        return 0

    # ---------- 复制
    for s, d in plan:
        if s is None:
            d.mkdir(parents=True, exist_ok=True)
            continue
        if not s.is_file():
            log("[FAIL] 源文件缺失: %s" % s)
            return 3
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(s), str(d))
        log("[copy] %s -> %s" % (s.name, d))

    # ---------- 拆 terms
    if not src_terms.is_file():
        log("[FAIL] 缺 terms.md: %s" % src_terms)
        return 3

    rows = parse_terms_table(read_text(src_terms))
    bourgeois_rows = []
    literary_rows = []
    for no, cells in rows:
        try:
            n = int(no)
        except ValueError:
            n = None
        if n is not None and 28 <= n <= 50:
            bourgeois_rows.append((no, cells))
        elif n is not None and 1 <= n <= 27:
            literary_rows.append((no, cells))
        else:
            log("[warn] 编号无法归属，跳过: %r %s" % (no, cells[1]))

    terms_dir = ROOT / "terms"
    write_text(terms_dir / ("%s.md" % BOURGEOIS), render_terms(bourgeois_rows))
    write_text(terms_dir / ("%s.md" % LITERARY), render_terms(literary_rows))
    log("[terms] %s: %d 条" % (BOURGEOIS, len(bourgeois_rows)))
    log("[terms] %s: %d 条" % (LITERARY, len(literary_rows)))

    index = {
        BOURGEOIS: {"file": "%s.md" % BOURGEOIS, "entries": len(bourgeois_rows)},
        LITERARY: {"file": "%s.md" % LITERARY, "entries": len(literary_rows)},
    }
    write_text(terms_dir / "_index.json", json.dumps(index, ensure_ascii=False, indent=2))
    log("[terms] _index.json 已写入")

    log("\n[ok] 迁移完成。下一步：")
    log("  python upstream/src/publish.py --id %s" % BOURGEOIS)
    log("  python downstream/src/render.py --id %s" % BOURGEOIS)
    log("  python downstream/src/build_index.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
