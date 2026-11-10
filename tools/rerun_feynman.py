#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rerun_feynman.py — 只重跑 pass9（费曼练习骨架）
=============================================

复用已有的 analysis.json，只重新生成费曼骨架，然后发布 + 重渲染。
供迭代 `prompts/pass9_feynman.md` 时快速验证，不必重跑整条流水线。

用法：
    python tools/rerun_feynman.py 20261109_xuanjian-xianzu
    python tools/rerun_feynman.py <id> --depth 5      # 换深度
    python tools/rerun_feynman.py <id> --resume       # 复用已缓存批次
    python tools/rerun_feynman.py <id> --no-render    # 只生成，不发布

退出码：
    0  成功
    3  缺少 analysis.json
    4  骨架校验未通过
    5  调用/发布失败
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
    ap = argparse.ArgumentParser(description="只重跑 pass9（费曼骨架）")
    ap.add_argument("article_id")
    ap.add_argument("--depth", type=int, default=3, choices=[1, 2, 3, 4, 5],
                    help="生成到第几层（默认 3）")
    ap.add_argument("--resume", action="store_true",
                    help="复用 analysis/pass.9_*.json 已缓存的批次响应")
    ap.add_argument("--no-render", action="store_true",
                    help="只生成骨架，不发布不渲染")
    args = ap.parse_args(argv)

    import pipeline as P
    from llm_client import LLMClient, LLMError

    pkg = ROOT / "corpus" / args.article_id
    analysis_p = pkg / "analysis" / "analysis.json"
    if not analysis_p.is_file():
        print("[FAIL] 缺少 analysis.json：%s" % analysis_p, file=sys.stderr)
        return 3

    analysis = json.loads(P.read_text(analysis_p))
    blocks = analysis.get("blocks") or []
    print("[info] %s：%d 个子块，目标深度 %d"
          % (args.article_id, len(blocks), args.depth), flush=True)

    client = LLMClient()
    if not client.available():
        print("[FAIL] 未配置 API Key（见 .env.example）", file=sys.stderr)
        return 5
    print("[llm] " + client.describe(), flush=True)

    agent_md = P.load_agent_prompt()
    try:
        feynman = P.run_pass9(args.article_id, analysis, client, agent_md,
                              depth=args.depth, resume=args.resume)
    except LLMError as e:
        print("[FAIL] " + str(e), file=sys.stderr)
        return 5

    try:
        import validate as V
        ok, errs, warns = V.validate_feynman(feynman, analysis)
        for w in warns:
            print("[warn] " + w)
        for e in errs[:10]:
            print("[schema] " + e)
        if not ok:
            print("[FAIL] 骨架未通过校验（已落盘，便于排查）", file=sys.stderr)
            return 4
        print("[validate] 费曼骨架校验通过")
    except SystemExit as e:
        print("[warn] 校验跳过：%s" % e)

    n_blocks = len(feynman.get("blocks") or {})
    n_layers = sum(len(v) for v in (feynman.get("blocks") or {}).values())

    if args.no_render:
        print("[ok] 骨架已生成：%d 子块 / %d 层（未发布）" % (n_blocks, n_layers))
        return 0

    print("[publish] 更新 deliver.json 并重渲染 …", flush=True)
    import publish as PUB
    rc = PUB.build(args.article_id, None, False, True)
    if rc != 0:
        print("[FAIL] 发布阶段退出码 %d" % rc, file=sys.stderr)
        return 5

    print("[ok] 完成：%d 子块 / %d 层，已重渲" % (n_blocks, n_layers))
    return 0


if __name__ == "__main__":
    sys.exit(main())
