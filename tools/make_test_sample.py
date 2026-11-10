#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_test_sample.py — 合成回归测试样本
=====================================

从已有文章包复制一份，改掉 article_id 与标题，生成**结构完全合法**的
第二篇文章包，用于验证多书管线（书架、幂等、术语隔离）。

⚠️ 这是**合成样本**：
   - analysis.json / article.md 的正文内容仍然来自源包（不做语义改写）；
   - 只替换 meta.title 与正文首行标题；
   - 因此图谱/正文内容与标题不匹配属预期，仅用于管线回归，不可当真实内容使用。

用法：
    python tools/make_test_sample.py
    python tools/make_test_sample.py --source 20261109_bourgeois \
        --target 20261026_literary_theory \
        --title "结构主义与后结构主义：从索绪尔到德里达（回归测试样本）"
    python tools/make_test_sample.py --dry-run
    python tools/make_test_sample.py --force      # 目标已存在时覆盖

生成后请执行：
    python upstream/src/publish.py --id <target> --auto-render
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "corpus"

DEFAULT_SOURCE = "20261109_bourgeois"
DEFAULT_TARGET = "20261026_literary_theory"
DEFAULT_TITLE = "结构主义与后结构主义：从索绪尔到德里达（回归测试样本）"

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


def replace_first_h1(text, new_title):
    """只替换正文的第一个 `# ` 标题行。"""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("# "):
            lines[i] = "# " + new_title
            return "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    # 没有 h1 就补一行
    return "# " + new_title + "\n\n" + text


def main(argv=None):
    ap = argparse.ArgumentParser(description="合成回归测试样本（复制源包并改标题/article_id）")
    ap.add_argument("--source", default=DEFAULT_SOURCE)
    ap.add_argument("--target", default=DEFAULT_TARGET)
    ap.add_argument("--title", default=DEFAULT_TITLE)
    ap.add_argument("--force", action="store_true", help="目标包已存在时覆盖")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    src = CORPUS / args.source
    dst = CORPUS / args.target

    if not src.is_dir():
        log("[FAIL] 源包不存在: %s" % src)
        return 3

    src_analysis = src / "analysis" / "analysis.json"
    src_articles = [
        src / "text" / "article.md",
        src / "text" / "article_with_examples.md",
    ]
    if not src_analysis.is_file():
        log("[FAIL] 源包缺 analysis.json: %s" % src_analysis)
        return 3

    if dst.exists() and not args.force:
        log("[FAIL] 目标包已存在: %s（加 --force 覆盖）" % dst)
        return 3

    log("=== 合成样本 ===")
    log("  source : %s" % args.source)
    log("  target : %s" % args.target)
    log("  title  : %s" % args.title)
    log("  提醒   : 正文仍是源包内容，仅用于管线回归")

    if args.dry_run:
        log("\n[dry-run] 未写入任何文件。")
        return 0

    # ---------- 复制目录骨架（不含 build/，由 render 重新生成）
    if dst.exists():
        shutil.rmtree(str(dst))
    (dst / "analysis").mkdir(parents=True, exist_ok=True)
    (dst / "text").mkdir(parents=True, exist_ok=True)
    (dst / "source").mkdir(parents=True, exist_ok=True)

    # ---------- analysis.json：改 meta.title + article_id（若存在）
    delivered_analysis = json.loads(read_text(src_analysis))
    meta = delivered_analysis.setdefault("meta", {})
    old_title = meta.get("title")
    meta["title"] = args.title
    meta["article_id"] = args.target          # P3 补丁字段，先按约定写入
    write_text(dst / "analysis" / "analysis.json",
               json.dumps(delivered_analysis, ensure_ascii=False, indent=2))
    log("[write] analysis/analysis.json  title: %r -> %r" % (old_title, args.title))

    # ---------- 正文：改首个 h1
    for p in src_articles:
        if not p.is_file():
            log("[warn] 源文件缺失，跳过: %s" % p)
            continue
        text = read_text(p)
        new_text = replace_first_h1(text, args.title)
        write_text(dst / "text" / p.name, new_text)
        log("[write] text/%s" % p.name)

    log("\n[ok] 样本已生成: %s" % dst)
    log("下一步：python upstream/src/publish.py --id %s --auto-render" % args.target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
