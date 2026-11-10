#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rerun_examples.py — 只重跑 pass7s（补充例子）
============================================

复用已有的 analysis.json 与 article.md，单独调用一次 pass7s 重新生成
`article_with_examples.md`，不动其他任何产物。

用途：调整了 pass7s 提示词（比如例子数量）后，不必重跑整条流水线。

用法：
    python tools/rerun_examples.py 20261109_xuanjian-xianzu
    python tools/rerun_examples.py 20261109_xuanjian-xianzu --dry-run

退出码：
    0  成功
    3  缺少输入
    5  调用失败
"""

import argparse
import json
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


def main(argv=None):
    ap = argparse.ArgumentParser(description="只重跑 pass7s 补充例子")
    ap.add_argument("article_id")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    import pipeline as P
    from llm_client import LLMClient, LLMError

    pkg = ROOT / "corpus" / args.article_id
    analysis_p = pkg / "analysis" / "analysis.json"
    article_p = pkg / "text" / "article.md"
    out_p = pkg / "text" / "article_with_examples.md"

    for p in (analysis_p, article_p):
        if not p.is_file():
            print("[FAIL] 缺少输入：%s" % p, file=sys.stderr)
            return 3

    analysis = json.loads(P.read_text(analysis_p))
    article_md = P.read_text(article_p)
    blocks = analysis.get("blocks") or []

    print("[info] %s：%d 个子块，正文 %d 字"
          % (args.article_id, len(blocks), len(article_md)), flush=True)

    if args.dry_run:
        print("[dry-run] 不调用模型")
        return 0

    client = LLMClient()
    if not client.available():
        print("[FAIL] 未配置 API Key", file=sys.stderr)
        return 5
    print("[llm] " + client.describe(), flush=True)

    agent_md = P.load_agent_prompt()
    try:
        out = P.call_text(client, agent_md, "pass7s",
                          {"article_md": article_md, "blocks": blocks})
    except LLMError as e:
        print("[FAIL] " + str(e), file=sys.stderr)
        return 5

    P.write_text(out_p, out.strip() + "\n")

    n = sum(1 for line in out.splitlines() if line.strip().startswith("> 例"))
    print("[ok] 已写回 %s（例子块 %d 个，%d 字）"
          % (out_p.name, n, len(out)), flush=True)
    print("     下一步：python upstream/src/publish.py --id %s --auto-render"
          % args.article_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
