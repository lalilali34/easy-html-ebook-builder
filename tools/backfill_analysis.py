#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backfill_analysis.py — 给已有 analysis.json 补齐 P1-P6 契约字段
==============================================================

补三样东西（幂等，可反复跑）：

1. `schema_version`: 顶层补 "1.0"                          （P5）
2. `meta.article_id`: 从包目录名补齐                        （P3）
3. `skeleton.blocks[].subblock_ids`: 按 id 前缀推断          （P2）

推断规则：大块 `b1` 的 subblock_ids = blocks 中所有以 `b1-` 开头的 id，
按它们在 blocks 数组里的原始顺序排列（即渲染顺序）。

**不修改任何分析内容**，只补结构性字段。

用法：
    python tools/backfill_analysis.py --all
    python tools/backfill_analysis.py --id 20261109_bourgeois
    python tools/backfill_analysis.py --all --dry-run
    python tools/backfill_analysis.py --all --force     # 覆盖已有 subblock_ids

退出码：
    0  成功（含"无需修改"）
    3  目标不存在
    5  解析失败
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "corpus"
SCHEMA_VERSION = "1.0"

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


def read_json(path):
    with open(str(path), "r", encoding="utf-8-sig", errors="strict") as f:
        return json.loads(f.read())


def write_json(path, obj):
    with open(str(path), "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(obj, ensure_ascii=False, indent=2))
        f.write("\n")


def backfill_one(article_id, force=False, dry_run=False):
    pkg = CORPUS / article_id
    p = pkg / "analysis" / "analysis.json"
    if not p.is_file():
        fail("%s: 缺少 analysis/analysis.json" % article_id)
        return 3

    try:
        data = read_json(p)
    except Exception as e:
        fail("%s: 解析失败 %s" % (article_id, e))
        return 5

    changes = []

    # --- P5: schema_version
    if data.get("schema_version") != SCHEMA_VERSION:
        old = data.get("schema_version")
        data["schema_version"] = SCHEMA_VERSION
        changes.append("schema_version: %r -> %r" % (old, SCHEMA_VERSION))

    # --- P3: meta.article_id
    meta = data.setdefault("meta", {})
    old_aid = meta.get("article_id")
    if old_aid != article_id:
        meta["article_id"] = article_id
        changes.append("meta.article_id: %r -> %r" % (old_aid, article_id))

    # --- P2: subblock_ids
    blocks = [b for b in (data.get("blocks") or []) if isinstance(b, dict)]
    all_ids = [b.get("id") for b in blocks if isinstance(b.get("id"), str)]

    skeleton_blocks = ((data.get("skeleton") or {}).get("blocks")) or []
    for sb in skeleton_blocks:
        if not isinstance(sb, dict):
            continue
        sid = sb.get("id")
        if not isinstance(sid, str):
            continue
        existing = sb.get("subblock_ids")
        inferred = [x for x in all_ids if x.startswith(sid + "-")]
        if existing and not force:
            # 已存在：只校验覆盖完整性，不覆盖
            same = list(existing) == inferred
            if not same:
                changes.append("skeleton.%s.subblock_ids 已存在但与推断不一致（保持原样；--force 覆盖）"
                               % sid)
            continue
        sb["subblock_ids"] = inferred
        changes.append("skeleton.%s.subblock_ids: %d 个 %s"
                       % (sid, len(inferred), inferred))

    if not changes:
        log("[skip] %s: 无需补全" % article_id)
        return 0

    log("[plan] %s" % article_id)
    for c in changes:
        log("    " + c)

    if dry_run:
        log("    [dry-run] 未写入")
        return 0

    write_json(p, data)
    log("[ok] %s: 已写回 analysis.json" % article_id)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="给 analysis.json 补齐 P1-P6 契约字段")
    ap.add_argument("--id", action="append", help="文章 id（可重复）")
    ap.add_argument("--all", action="store_true", help="处理 corpus/ 下全部文章包")
    ap.add_argument("--force", action="store_true", help="覆盖已有的 subblock_ids")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    ids = list(args.id or [])
    if args.all:
        if not CORPUS.is_dir():
            fail("corpus/ 不存在")
            return 3
        ids.extend(sorted(p.name for p in CORPUS.iterdir()
                          if p.is_dir() and (p / "analysis" / "analysis.json").is_file()))
    if not ids:
        ap.error("需要 --id <article_id> 或 --all")

    rc = 0
    for aid in ids:
        rc = max(rc, backfill_one(aid, args.force, args.dry_run))
    return rc


if __name__ == "__main__":
    sys.exit(main())
