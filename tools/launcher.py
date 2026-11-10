#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
launcher.py — 拖拽启动器（打包成 exe 用）
=========================================

把 .txt / .md 文件拖到 ebook-pipeline.exe 上，自动跑完整流程：
    入库 → 结构化分析 → 发布 → 渲染 → 更新书架

命令行同样可用：
    ebook-pipeline.exe "inbox\\某篇.md"

设计要点：
- exe 本身只是「启动器」，**不打包项目代码**；
  运行时把 `<exe目录>/upstream/src` 加进 sys.path，import 项目里的 full_auto。
  这样改了 .py 不用重新打包 exe。
- 项目根 = exe 所在目录（frozen 模式）。
"""

import os
import sys
import traceback
from pathlib import Path

# ---------------------------------------------------------------------------
# 静态引用：项目代码是动态 import 的，PyInstaller 静态分析看不到它们的依赖，
# 必须在启动器里显式引用一遍，否则打包出的 exe 会缺 json / urllib 等标准库。
# 这些导入本身不参与运行逻辑，只为让打包器收集模块。
# ---------------------------------------------------------------------------
import argparse        # noqa: F401
import datetime        # noqa: F401
import hashlib         # noqa: F401
import html            # noqa: F401  （render.py / build_index.py 用）
import importlib       # noqa: F401
import json            # noqa: F401
import re              # noqa: F401
import shutil          # noqa: F401
import subprocess      # noqa: F401
import time            # noqa: F401
import urllib.error    # noqa: F401
import urllib.request  # noqa: F401

SUPPORTED = (".txt", ".md")


def setup_console():
    """Windows 控制台切 UTF-8，避免中文日志乱码。"""
    if sys.platform == "win32":
        try:
            os.system("chcp 65001 > nul")
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def project_root():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # 源码模式：tools/launcher.py -> 项目根
    return Path(__file__).resolve().parent.parent


def main():
    setup_console()
    root = project_root()

    print("=" * 60)
    print("  ebook-pipeline 拖拽启动器")
    print("  项目目录：%s" % root)
    print("=" * 60)

    targets = sys.argv[1:]
    if not targets:
        print("\n用法：")
        print("  1) 把 .txt / .md 文件直接拖到这个 exe 上")
        print("  2) 或：ebook-pipeline.exe \"inbox\\某篇.md\"")
        return 2

    src = str(root / "upstream" / "src")
    if src not in sys.path:
        sys.path.insert(0, src)

    try:
        import importlib
        # 动态导入：PyInstaller 不会把它静态打进 exe，
        # 运行时从项目目录加载最新代码，改 .py 无需重新打包。
        full_auto = importlib.import_module("full_auto")
    except Exception:
        print("\n[FAIL] 无法加载项目代码，请确认 exe 放在项目根目录：")
        print("        %s" % root)
        traceback.print_exc()
        return 5

    rc = 0
    for raw in targets:
        p = Path(raw)

        if p.suffix.lower() not in SUPPORTED:
            print("\n[skip] 不支持的格式：%s" % p.name)
            print("       目前支持 %s；.srt/.vtt 请先转成 txt。"
                  % " / ".join(SUPPORTED))
            rc = max(rc, 3)
            continue

        if not p.is_file():
            # 允许只写文件名（相对 inbox/）
            cand = root / "inbox" / raw
            if cand.is_file():
                p = cand
            else:
                print("\n[skip] 文件不存在：%s" % raw)
                rc = max(rc, 3)
                continue

        print("\n" + "-" * 60)
        print(" 处理：%s" % p.name)
        print("-" * 60)

        try:
            rc = max(rc, full_auto.main(["--file", str(p)]))
        except SystemExit as e:
            rc = max(rc, e.code if isinstance(e.code, int) else 0)
        except Exception:
            traceback.print_exc()
            rc = max(rc, 1)

    print("\n" + "=" * 60)
    print(" 完成，退出码 %d" % rc)
    print("=" * 60)
    return rc


if __name__ == "__main__":
    try:
        code = main()
    except Exception:
        traceback.print_exc()
        code = 1

    # 双击运行时窗口别一闪而过
    if getattr(sys, "frozen", False):
        try:
            input("\n按回车关闭窗口…")
        except EOFError:
            pass

    sys.exit(code)
