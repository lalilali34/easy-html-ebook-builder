#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
import_feynman.py — 把浏览器导出的费曼 JSON 拆成单块记录文件
================================================================

浏览器「练习」Tab 导出的 `feynman_<article_id>.json` 是一个整篇文件，
本工具把它拆成规格要求的单块文件：

    feynman/<article_id>/<subblock_id>.json

用法：
    python tools/import_feynman.py "C:\\Users\\...\\feynman_20261109_xuanjian-xianzu.json"
    python tools/import_feynman.py <导出文件> --out-dir feynman/<id> --dry-run

退出码：
    0  成功
    3  输入文件无效
    5  写入失败
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def main(argv=None):
    ap = argparse.ArgumentParser(description="拆分费曼导出 JSON 为单块记录")
    ap.add_argument("path", help="浏览器导出的 feynman_<id>.json")
    ap.add_argument("--out-dir", help="输出目录（默认 feynman/<article_id>/）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    src = Path(args.path)
    if not src.is_file():
        print("[FAIL] 文件不存在：%s" % src, file=sys.stderr)
        return 3

    try:
        data = json.loads(src.read_text(encoding="utf-8-sig"))
    except Exception as e:
        print("[FAIL] 解析失败：%s" % e, file=sys.stderr)
        return 3

    aid = data.get("article_id")
    blocks = data.get("blocks")
    if not aid or not isinstance(blocks, dict) or not blocks:
        print("[FAIL] 缺少 article_id 或 blocks", file=sys.stderr)
        return 3

    out_dir = Path(args.out_dir) if args.out_dir else (ROOT / "feynman" / aid)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir

    print("[info] article_id=%s，%d 个子块" % (aid, len(blocks)))
    print("[info] 输出目录：%s" % out_dir)

    if args.dry_run:
        for sid in sorted(blocks):
            print("  (dry) %s.json" % sid)
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for sid, rec in sorted(blocks.items()):
        # 基本完整性检查：块记录必须带 layers
        if not isinstance(rec, dict) or not isinstance(rec.get("layers"), list):
            print("[warn] 跳过结构异常的块：%s" % sid)
            continue
        target = out_dir / ("%s.json" % sid)
        with open(str(target), "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(rec, ensure_ascii=False, indent=2))
            f.write("\n")
        n += 1

    print("[ok] 已写入 %d 个块记录 -> %s" % (n, out_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
