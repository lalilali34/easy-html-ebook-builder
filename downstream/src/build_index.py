#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_index.py — 书架聚合器
===========================

扫描 corpus/*/deliver.json（仅 status == ready 且已渲染出 HTML 的），
生成 site/index.html。

纯标准库，Python 3.8+。

用法：
    python downstream/src/build_index.py
    python downstream/src/build_index.py --check   # 只报数，不写文件

退出码：
    0  成功（含"没有可展示文章"的空书架）
    1  未捕获异常
    5  读取/解析失败
"""

import argparse
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "corpus"
SITE = ROOT / "site"
FONTS_REL = "../downstream/assets/fonts"

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
        return f.read()


def write_text(path, text):
    with open(str(path), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def load_json(path):
    return json.loads(read_text(path))


def esc(s):
    import html as _html
    return _html.escape("" if s is None else str(s), quote=True)


def collect():
    """返回 [(article_id, deliver_dict, html_abs_path_or_None), ...]，按 id 倒序。"""
    items = []
    if not CORPUS.is_dir():
        return items
    for pkg in sorted(CORPUS.iterdir()):
        if not pkg.is_dir():
            continue
        deliver_p = pkg / "deliver.json"
        if not deliver_p.is_file():
            continue
        try:
            d = load_json(deliver_p)
        except Exception as e:
            log("[warn] 跳过 %s: deliver.json 解析失败 (%s)" % (pkg.name, e))
            continue
        if d.get("status") != "ready":
            continue
        html_p = pkg / "build" / ("%s.html" % pkg.name)
        items.append((pkg.name, d, html_p if html_p.is_file() else None))
    items.sort(key=lambda x: x[0], reverse=True)
    return items


CARD_TPL = """    <a class="book-card{extra_cls}" href="{href}">
      <div class="card-id">{article_id}</div>
      <h2 class="card-title">{title}</h2>
      <div class="card-stats">{stats}</div>
      <div class="card-foot">{foot}</div>
    </a>"""

PAGE_TPL = """<!DOCTYPE html>
<html lang="zh-CN" data-theme="1">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>书架 · 电子书流水线</title>
<style>
@font-face {{
  font-family: 'Hanyi Scholar';
  src: url('{fonts}/hanyi.woff2') format('woff2');
  font-display: swap;
}}
* {{ box-sizing: border-box; }}
html, body {{
  margin: 0;
  padding: 0;
  background: linear-gradient(to bottom, #1e1e2f 0%, #11111b 100%);
  color: #d1d5db;
  font-family: 'Hanyi Scholar', serif;
  min-height: 100vh;
}}
body {{ padding: 3rem 2rem 5rem; max-width: 1400px; margin: 0 auto; }}
header {{ text-align: center; margin-bottom: 3rem; }}
h1 {{
  font-size: 42px; font-weight: 600; color: #fff;
  margin: 0 0 0.7rem; letter-spacing: 0.04em;
}}
.sub {{ font-size: 17px; opacity: 0.55; }}
.grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 1.4rem;
}}
.book-card {{
  display: block;
  text-decoration: none;
  color: inherit;
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.09);
  border-radius: 14px;
  padding: 1.4rem 1.5rem 1.2rem;
  transition: transform 0.18s ease, background 0.18s ease, border-color 0.18s ease;
}}
.book-card:hover {{
  transform: translateY(-3px);
  background: rgba(255,255,255,0.09);
  border-color: rgba(59,130,246,0.55);
}}
.book-card.pending {{ opacity: 0.42; cursor: not-allowed; }}
.card-id {{
  font-family: ui-monospace, Consolas, monospace;
  font-size: 13px;
  opacity: 0.5;
  letter-spacing: 0.03em;
  margin-bottom: 0.6rem;
}}
.card-title {{
  font-size: 24px;
  line-height: 1.55;
  color: #fff;
  margin: 0 0 0.9rem;
  font-weight: 600;
}}
.card-stats {{ font-size: 15px; opacity: 0.65; line-height: 1.8; }}
.card-foot {{
  margin-top: 0.9rem;
  padding-top: 0.8rem;
  border-top: 1px solid rgba(255,255,255,0.07);
  font-size: 14px;
  opacity: 0.45;
}}
.badge {{
  display: inline-block;
  font-size: 12px;
  padding: 0.1rem 0.5rem;
  border-radius: 999px;
  background: rgba(59,130,246,0.22);
  color: #93c5fd;
  margin-left: 0.45rem;
  vertical-align: middle;
}}
.empty {{
  text-align: center;
  opacity: 0.5;
  font-size: 19px;
  margin-top: 5rem;
  line-height: 2;
}}
</style>
</head>
<body>
<header>
  <h1>书架</h1>
  <div class="sub">{count} 篇 · 生成于 {generated_at}</div>
</header>
{cards}
</body>
</html>
"""


def card_html(article_id, d, html_p):
    title = d.get("title") or article_id
    stats = d.get("stats") or {}
    bits = []
    if stats.get("skeleton_blocks"):
        bits.append("%s 大块" % stats["skeleton_blocks"])
    if stats.get("subblocks"):
        bits.append("%s 子块" % stats["subblocks"])
    if stats.get("relations"):
        bits.append("%s 条关系" % stats["relations"])
    stats_line = " · ".join(str(b) for b in bits) if bits else "—"

    generated = (d.get("generated_at") or "")[:16].replace("T", " ")
    count_terms = ""
    for a in (d.get("artifacts") or []):
        if a.get("kind") == "terms" and a.get("entry_count"):
            count_terms = '<span class="badge">%s 术语</span>' % a["entry_count"]

    pending = html_p is None
    return CARD_TPL.format(
        extra_cls=" pending" if pending else "",
        href="#" if pending else "../corpus/%s/build/%s.html" % (esc(article_id), esc(article_id)),
        article_id=esc(article_id),
        title=esc(title),
        stats=esc(stats_line) + count_terms,
        foot=("尚未渲染" if pending else "已渲染") + (" · " + esc(generated) if generated else ""),
    )


def build(check_only=False):
    items = collect()

    cards = []
    for article_id, d, html_p in items:
        cards.append(card_html(article_id, d, html_p))

    if not cards:
        body = ('<p class="empty">还没有已发布的文章。<br>'
                '在上游跑完并写出 <code>deliver.json</code> 后，重新执行 build_index.py。</p>')
    else:
        body = '<div class="grid">\n' + "\n".join(cards) + "\n</div>"

    page = PAGE_TPL.format(
        fonts=FONTS_REL,
        count=len(items),
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        cards=body,
    )

    rendered = sum(1 for _, _, h in items if h is not None)
    log("[info] 文章包 %d 个（已渲染 %d / 待渲染 %d）"
        % (len(items), rendered, len(items) - rendered))

    if check_only:
        return 0

    SITE.mkdir(parents=True, exist_ok=True)
    out = SITE / "index.html"
    tmp = SITE / "index.html.tmp"
    write_text(tmp, page)
    os.replace(str(tmp), str(out))
    log("[ok] 书架已更新 -> %s (%d bytes)" % (out, out.stat().st_size))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="书架聚合器")
    ap.add_argument("--check", action="store_true", help="只统计，不写 index.html")
    args = ap.parse_args(argv)
    try:
        return build(args.check)
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
