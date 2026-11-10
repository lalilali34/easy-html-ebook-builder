#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_analysis_quotes.py — 修补 analysis.json 里引文/要点的 ASR 错字
====================================================================

老文章（pass0 之前处理）的 raw.md 可能已丢失，无法重跑流水线，
但 `author_says` / `key_points` 里的错字可以在数据层直接修。

流程：
  1. 收集 blocks[].author_says[].text 和 key_points[]
  2. 调 pass0 检测错字（只针对这些引文，上下文足够）
  3. 只应用 confidence=high 的修正
  4. 备份原 analysis.json，写回修正版
  5. 可选：重新 publish + 渲染

用法：
    python tools/fix_analysis_quotes.py 20261109_bourgeois --dry-run
    python tools/fix_analysis_quotes.py 20261109_bourgeois --apply

退出码：0 成功 / 3 输入无效 / 4 校验失败 / 5 调用失败
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "upstream" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def collect_texts(analysis):
    """收集所有需要检查的引文/要点文本，返回 [(定位描述, 文本)]。"""
    items = []
    for b in (analysis.get("blocks") or []):
        if not isinstance(b, dict):
            continue
        bid = b.get("id", "?")
        for i, s in enumerate(b.get("author_says") or []):
            if isinstance(s, dict):
                # 实际字段是 quote / paraphrase（早期也有 text）
                for key in ("quote", "paraphrase", "text"):
                    t = s.get(key) or ""
                    if t.strip():
                        items.append(
                            ("blocks.%s.author_says[%d].%s" % (bid, i, key), t))
            elif isinstance(s, str) and s.strip():
                items.append(("blocks.%s.author_says[%d]" % (bid, i), s))
        for i, k in enumerate(b.get("key_points") or []):
            if isinstance(k, str) and k.strip():
                items.append(("blocks.%s.key_points[%d]" % (bid, i), k))
    return items


def apply_fix(analysis, corrections):
    """把 high 置信度的修正应用到 analysis 的关键字段上。"""
    applied = []
    for c in corrections:
        if not isinstance(c, dict):
            continue
        wrong = (c.get("wrong") or "").strip()
        right = (c.get("right") or "").strip()
        if not wrong or not right or wrong == right:
            continue
        if (c.get("confidence") or "").lower() != "high":
            continue

        hit = False
        for b in (analysis.get("blocks") or []):
            if not isinstance(b, dict):
                continue
            for s in (b.get("author_says") or []):
                if not isinstance(s, dict):
                    continue
                for key in ("quote", "paraphrase", "text"):
                    v = s.get(key)
                    if isinstance(v, str) and wrong in v:
                        s[key] = v.replace(wrong, right)
                        hit = True
            kps = b.get("key_points") or []
            for i, k in enumerate(kps):
                if isinstance(k, str) and wrong in k:
                    kps[i] = k.replace(wrong, right)
                    hit = True
        if hit:
            applied.append(c)
    return applied


def main(argv=None):
    ap = argparse.ArgumentParser(description="修补 analysis.json 里的 ASR 错字")
    ap.add_argument("article_id")
    ap.add_argument("--dry-run", action="store_true", help="只检测，不写文件")
    ap.add_argument("--apply", action="store_true", help="写回并重新发布渲染")
    ap.add_argument("--no-render", action="store_true", help="写回但不发布/渲染")
    args = ap.parse_args(argv)

    import pipeline as P
    from llm_client import LLMClient, LLMError

    pkg = ROOT / "corpus" / args.article_id
    ap_json = pkg / "analysis" / "analysis.json"
    if not ap_json.is_file():
        print("[FAIL] 缺少 analysis.json", file=sys.stderr)
        return 3

    analysis = json.loads(ap_json.read_text(encoding="utf-8-sig"))
    items = collect_texts(analysis)
    print("[info] 收集到 %d 条引文/要点" % len(items))

    if not items:
        print("[FAIL] 没有可检查的文本", file=sys.stderr)
        return 3

    # 拼成一段供 pass0 检查（带定位标记，方便回读）
    blob = "\n".join("[%d] %s" % (i + 1, t) for i, (_, t) in enumerate(items))

    client = LLMClient()
    if not client.available():
        print("[FAIL] 未配置 API Key", file=sys.stderr)
        return 5
    print("[llm] " + client.describe())

    try:
        raw = P.call_json_cached(client, P.load_agent_prompt(), "pass0",
                                 {"text": blob}, pkg / "analysis",
                                 False, tag="quotes")
    except LLMError as e:
        print("[FAIL] " + str(e), file=sys.stderr)
        return 5

    corrections = raw.get("corrections") if isinstance(raw, dict) else []
    corrections = [c for c in (corrections or []) if isinstance(c, dict)]

    high = [c for c in corrections
            if (c.get("confidence") or "").lower() == "high"]
    print("[pass0] 发现 %d 条，其中 high %d 条" % (len(corrections), len(high)))
    for c in corrections:
        mark = "✔" if (c.get("confidence") or "").lower() == "high" else " "
        print("  %s [%s] %s -> %s" % (mark, c.get("confidence"),
                                      c.get("wrong"), c.get("right")))

    if args.dry_run or not high:
        print("[dry-run] 未写文件" if args.dry_run else "[info] 没有 high 置信度修正")
        return 0

    applied = apply_fix(analysis, corrections)
    backup = ap_json.with_suffix(".json.bak")
    shutil.copy2(str(ap_json), str(backup))
    print("[backup] %s" % backup.name)

    ap_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
    print("[ok] 已应用 %d 条修正" % len(applied))

    # 校验
    try:
        import validate as V
        ok, errs, warns = V.validate_analysis(analysis,
                                              expected_article_id=args.article_id)
        for w in warns:
            print("[schema-warn] " + w)
        for e in errs[:10]:
            print("[schema] " + e)
        if not ok:
            print("[FAIL] 修正后未通过校验（备份在 .bak）", file=sys.stderr)
            return 4
        print("[validate] 校验通过")
    except SystemExit as e:
        print("[warn] 校验跳过：%s" % e)

    if args.no_render:
        return 0

    import publish as PUB
    rc = PUB.build(args.article_id, None, False, True)
    return 0 if rc == 0 else 5


if __name__ == "__main__":
    sys.exit(main())
