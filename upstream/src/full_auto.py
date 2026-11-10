#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
full_auto.py — 一条命令跑完全程
===============================

    python upstream/src/full_auto.py --file inbox/xxx.txt

做的事：

    1. txt  -> inbox_ingest 入库（建 corpus/<id>/ 骨架、raw.md）
    2. raw  -> pipeline 跑 pass1–pass8（超长自动分块压缩）
    3. 产物 -> publish --auto-render（deliver.json → HTML → 书架）

也支持直接传已入库的文章 id：

    python upstream/src/full_auto.py --file 20261109_bourgeois

无 API Key 时用 --dry-run 只验证管线（生成 *.dryrun.*，不覆盖正式文件、不发布）：

    python upstream/src/full_auto.py --file inbox/xxx.txt --dry-run

退出码：
    0  成功
    3  输入无效
    4  产物校验未通过
    5  调用/发布失败
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "corpus"
SRC = Path(__file__).resolve().parent

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

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


def resolve_article(arg, slug=None, date_str=None):
    """
    返回 (article_id, error)。
    arg 可以是：txt 文件路径 / 已入库的 id / corpus 下的目录路径。
    """
    p = Path(arg)

    # 相对路径：先按当前目录找，找不到再回退到仓库根
    if not p.is_absolute() and not p.is_file():
        cand = ROOT / p
        if cand.is_file():
            p = cand

    # 1) 纯文本 / Markdown → 先入库
    if p.suffix.lower() in (".txt", ".md") and p.is_file():
        import inbox_ingest
        log("[step 1/3] 入库：%s" % p.name)
        aid, err = inbox_ingest.ingest_file(
            p, slug_override=slug, date_str=date_str)
        if err:
            return None, err
        return aid, None

    # 2) 直接给 id
    if (CORPUS / arg).is_dir():
        return arg, None

    # 3) 给 corpus 下的路径
    if p.is_dir() and p.parent.resolve() == CORPUS.resolve():
        return p.name, None

    return None, ("无法识别输入：%s\n"
                  "  给 .txt 文件路径，或已入库的 article_id（corpus/ 下的目录名）" % arg)


def main(argv=None):
    ap = argparse.ArgumentParser(description="一条命令跑完入库→分析→渲染→书架")
    ap.add_argument("--file", required=True,
                    help="inbox 下的 txt，或已入库的 article_id")
    ap.add_argument("--dry-run", action="store_true",
                    help="不调模型、不发布，只验证管线")
    ap.add_argument("--max-chars", type=int, default=24000,
                    help="超过该字数启用分块压缩（默认 24000，约 64K 上下文的 1/3）")
    ap.add_argument("--resume", action="store_true",
                    help="复用已保存的 pass 响应，只重跑缺失部分")
    ap.add_argument("--slug", help="入库时手动指定 slug")
    ap.add_argument("--date", help="入库时覆盖日期 YYYYMMDD")
    args = ap.parse_args(argv)

    aid, err = resolve_article(args.file, args.slug, args.date)
    if err:
        fail(err)
        return 3
    log("[article] %s" % aid)

    # ---- 2. 分析
    import pipeline as pipe
    from llm_client import LLMClient, LLMError

    log("[step 2/3] 结构化分析（%s）"
        % ("dry-run" if args.dry_run else "调用模型"))
    try:
        client = None if args.dry_run else LLMClient()
        if client is not None:
            log("[llm] " + client.describe())
        rc = pipe.run(aid, args.dry_run, args.max_chars, client, args.resume)
    except LLMError as e:
        fail(str(e))
        return 5

    if rc != 0:
        fail("分析阶段退出码 %d，终止后续步骤" % rc)
        return rc

    if args.dry_run:
        log("\n[dry-run] 已完成。产出为 *.dryrun.*，未发布、未入库书架。")
        log("          配好 .env 后去掉 --dry-run 即可正式运行。")
        return 0

    # ---- 3. 发布 + 渲染 + 书架（进程内调用，兼容 exe 打包）
    log("[step 3/3] 发布并渲染")
    try:
        import publish as _publish
        rc2 = _publish.build(aid, None, False, True)
    except SystemExit as e:
        rc2 = e.code if isinstance(e.code, int) else 1
    if rc2 != 0:
        fail("发布阶段退出码 %d" % rc2)
        return 5

    log("\n[ok] 全流程完成：corpus/%s/build/%s.html" % (aid, aid))
    return 0


if __name__ == "__main__":
    sys.exit(main())
