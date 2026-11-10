#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render.py — 文章包合一渲染器（正文 / 图谱 / 术语 三 Tab）
===========================================================

读取 corpus/<id>/deliver.json，产出单文件 HTML：
    corpus/<id>/build/<id>.html

纯标准库，Python 3.8+。不联网、不调用模型、不读写包外文件（除 terms/ 与 downstream/）。

用法：
    python downstream/src/render.py --id 20261109_bourgeois
    python downstream/src/render.py --id 20261109_bourgeois --force
    python downstream/src/render.py --all
    python downstream/src/render.py --id 20261109_bourgeois --check-only

退出码：
    0  成功 / 幂等命中跳过
    1  未捕获异常
    2  deliver.json 缺失，或 status != ready
    3  产物缺失 / sha256 不匹配
    4  checks 未全部 pass
    5  模板 / 主题 / 输入读取或解析失败
"""

import argparse
import hashlib
import html
import json
import os
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------- 路径常量

ROOT = Path(__file__).resolve().parents[2]      # downstream/src/render.py -> <repo>
CORPUS = ROOT / "corpus"
CONTRACT = ROOT / "contract"
TERMS_DIR = ROOT / "terms"
PERSONAL_DIR = ROOT / "personal_terms"
DOWNSTREAM = ROOT / "downstream"
THEMES = DOWNSTREAM / "themes.md"
TEMPLATE = DOWNSTREAM / "templates" / "tab-shell.html"
FONTS = DOWNSTREAM / "assets" / "fonts"

RENDERER_VERSION = "1.0.0"

# 控制台中文输出（Windows 默认 GBK 会炸）
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


# ---------------------------------------------------------------- 基础工具

def log(msg):
    print(msg, flush=True)


def die(code, msg):
    print("[FAIL] " + str(msg), file=sys.stderr, flush=True)
    sys.exit(code)


def read_text(path):
    """UTF-8 读取，容忍 BOM，统一 LF。"""
    with open(str(path), "r", encoding="utf-8-sig", errors="strict") as f:
        return f.read().replace("\r\n", "\n").replace("\r", "\n")


def write_text(path, text):
    """UTF-8 写，统一 LF，无 BOM。"""
    with open(str(path), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def load_json(path):
    return json.loads(read_text(path))


def sha256_file(path):
    h = hashlib.sha256()
    with open(str(path), "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def deliver_fingerprint(deliver):
    """
    deliver.json 的「语义指纹」：剔除 generated_at 这类每次发布都会变的字段。
    否则 publish -> auto-render 每次都判定输入变化，幂等直接失效。
    title / artifacts(sha256) / stats / checks 的变化仍然会影响指纹，这是要的。
    """
    d = dict(deliver)
    d.pop("generated_at", None)
    payload = json.dumps(d, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def esc(s):
    """正文文本转义（不转义引号）。"""
    return html.escape("" if s is None else str(s), quote=False)


def attr(s):
    """属性值转义（转义引号）。"""
    return html.escape("" if s is None else str(s), quote=True)


def load_enums():
    p = CONTRACT / "enums.json"
    if not p.is_file():
        die(5, "缺少契约文件: %s" % p)
    return load_json(p)


# ---------------------------------------------------------------- 术语解析

class Term(object):
    """terms/<id>.md 中的一行。"""
    __slots__ = ("name", "aliases", "type_id", "desc", "link", "scope", "note")

    def __init__(self, name, aliases, type_id, desc, link, scope, note):
        self.name = name
        self.aliases = aliases
        self.type_id = type_id
        self.desc = desc
        self.link = link
        self.scope = scope
        self.note = note

    @property
    def forms(self):
        out = [self.name]
        for a in self.aliases:
            if a and a != self.name:
                out.append(a)
        return out


def parse_terms_md(text, source=""):
    """
    解析 8 列 Markdown 表格：
    | 编号 | 词条名 | 别名/匹配形式 | 类型(1-5) | 解释文字 | 链接 | 匹配范围 | 排除/备注 |
    编号列允许为空（渲染时动态编号）。
    """
    terms = []
    seen = set()
    for lineno, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 8:
            continue
        if cells[0] and set(cells[0]) <= set("-: "):
            continue                                   # 分隔行 |---|---|
        if "词条名" in cells[1]:
            continue                                   # 表头
        _no, name, alias_raw, type_id, desc, link, scope, note = cells[:8]
        if not name:
            continue
        if name in seen:
            log("[warn] %s 第 %d 行: 词条重复，已忽略: %s" % (source or "terms", lineno, name))
            continue
        seen.add(name)
        aliases = [a.strip() for a in re.split(u"[\u3001,\uff0c]", alias_raw) if a.strip()]
        tid = type_id.strip()
        if tid not in ("1", "2", "3", "4", "5"):
            log("[warn] %s 第 %d 行: 类型非法 (%s)，按 2 处理: %s"
                % (source or "terms", lineno, tid, name))
            tid = "2"
        terms.append(Term(name, aliases, tid, desc, link, scope, note))
    return terms


class PersonalTerm(object):
    """personal_terms/<id>.md 中的一个条目。"""
    __slots__ = ("name", "matches", "scope", "hide", "body")

    def __init__(self, name, matches, scope, hide, body):
        self.name = name
        self.matches = matches
        self.scope = scope
        self.hide = hide
        self.body = body


def parse_personal_terms(text, source=""):
    """
    解析个人术语文件。返回 (terms, warnings)。

    格式（最小锚点，自由文本区不限）：
        ## 词条名
        match: a, b      ← 可选，缺省用词条名
        scope: 布迪厄     ← 可选
        hide: false      ← 可选
        （空行后为自由文本）
    """
    terms, warns = [], []
    if not text or not text.strip():
        return terms, warns

    blocks = re.split(r"(?m)^##\s+", text)
    if len(blocks) <= 1:
        warns.append("%s: 未找到任何 '## 词条名' 条目，已忽略整个文件"
                     % (source or "personal_terms"))
        return terms, warns

    for idx, blk in enumerate(blocks[1:], 1):
        lines = blk.splitlines()
        if not lines:
            continue
        name = lines[0].strip()
        if not name:
            warns.append("%s: 第 %d 个条目缺少词条名，已跳过"
                         % (source or "personal_terms", idx))
            continue

        match_raw = ""
        scope = ""
        hide = False
        body_lines = []
        in_header = True

        for ln in lines[1:]:
            s = ln.strip()
            if in_header:
                if not s:
                    in_header = False
                    continue
                low = s.lower()
                if low.startswith("match:"):
                    match_raw = s[6:].strip()
                    continue
                if low.startswith("scope:"):
                    scope = s[6:].strip()
                    continue
                if low.startswith("hide:"):
                    hide = s[5:].strip().lower() in ("true", "1", "yes", "是")
                    continue
                in_header = False
                body_lines.append(ln)
            else:
                body_lines.append(ln)

        matches = [m.strip() for m in re.split(u"[,，、]", match_raw) if m.strip()]
        if not matches:
            matches = [name]

        terms.append(PersonalTerm(name, matches, scope, hide,
                                  "\n".join(body_lines).strip()))

    return terms, warns


class TermMatcher(object):
    """
    最长匹配优先的术语标记器。
    - 在「已 HTML 转义」的文本上工作（调用方负责先 esc）。
    - 用单条正则的 alternation 实现：同一位置按长度降序尝试，天然最长优先。
    - finditer 不重叠，天然防止重复标注。
    """

    def __init__(self, terms, personal=None):
        self.terms = terms
        self.personal = personal or []

        # --- 系统层
        self.by_form = {}
        pairs = []
        for t in terms:
            for f in t.forms:
                if not f:
                    continue
                key = esc(f)
                if key in self.by_form:
                    continue                     # 同形归先到者
                self.by_form[key] = t
                pairs.append(key)
        pairs.sort(key=lambda x: (-len(x), x))
        self.forms = pairs
        self._rx = re.compile("|".join(re.escape(p) for p in pairs)) if pairs else None

        # --- 个人层
        self.pers_by_form = {}
        pers_pairs = []
        for p in self.personal:
            for f in p.matches:
                if not f:
                    continue
                key = esc(f)
                if key in self.pers_by_form:
                    continue
                self.pers_by_form[key] = p
                pers_pairs.append(key)
        pers_pairs.sort(key=lambda x: (-len(x), x))
        self._pers_rx = (re.compile("|".join(re.escape(p) for p in pers_pairs))
                         if pers_pairs else None)

        self.marked = {}                         # 词条名 -> 标记次数
        self.forms_seen = {}                     # 词条名 -> 命中的匹配形式集合
        self.personal_seen = {}                  # 个人条目名 -> 命中的形式列表
        self.dropped_personal = 0                # 因与系统重叠被丢弃的个人命中数

    def count(self, text_esc):
        """统计全文出现次数（词条名 -> 次数）。"""
        out = {}
        if not self._rx:
            return out
        for m in self._rx.finditer(text_esc):
            t = self.by_form.get(m.group(0))
            if t is not None:
                out[t.name] = out.get(t.name, 0) + 1
        return out

    def highlight(self, text_esc):
        """
        返回已标记 HTML。累加 marked 计数。

        系统与个人两层在同一次扫描里按区间合并：
          只有系统      -> <span class="term">
          只有个人      -> <span class="term-personal">
          区间完全一致  -> 一个 span 双属性（hide 时只留 data-personal）
          区间部分重叠  -> 系统优先，个人丢弃并计入 dropped_personal
        """
        if not self._rx and not self._pers_rx:
            return text_esc

        spans = {}          # (start, end) -> [kind, term, personal, form]

        if self._rx:
            for m in self._rx.finditer(text_esc):
                t = self.by_form.get(m.group(0))
                if t is None:
                    continue
                spans[(m.start(), m.end())] = ["sys", t, None, m.group(0)]

        if self._pers_rx:
            sys_spans = list(spans.keys())
            for m in self._pers_rx.finditer(text_esc):
                p = self.pers_by_form.get(m.group(0))
                if p is None:
                    continue
                key = (m.start(), m.end())
                if key in spans:
                    spans[key][0] = "both"
                    spans[key][2] = p
                    continue
                if any(not (m.end() <= s0 or m.start() >= e0) for s0, e0 in sys_spans):
                    self.dropped_personal += 1
                    continue
                spans[key] = ["pers", None, p, m.group(0)]

        if not spans:
            return text_esc

        parts = []
        pos = 0
        for key in sorted(spans.keys()):
            s, e = key
            if s < pos:
                continue
            kind, t, p, form = spans[key]
            parts.append(text_esc[pos:s])
            parts.append(self._render_span(kind, t, p, form))

            if t is not None:
                self.marked[t.name] = self.marked.get(t.name, 0) + 1
                self.forms_seen.setdefault(t.name, set()).add(form)
            if p is not None:
                self.personal_seen.setdefault(p.name, []).append(form)
            pos = e

        parts.append(text_esc[pos:])
        return "".join(parts)

    def _render_span(self, kind, t, p, form_esc):
        """按命中类型生成 span。data-term / data-pers-name 供前端笔记编辑定位。"""
        if kind == "sys":
            inner = ('<span class="term term-type-%s" data-tooltip="%s" data-term="%s">%s</span>'
                     % (attr(t.type_id), attr(t.desc), attr(t.name), form_esc))
            if t.link:
                return ('<a href="%s" target="_blank" rel="noopener">%s</a>'
                        % (attr(t.link), inner))
            return inner

        if kind == "pers":
            return ('<span class="term-personal term-personal-only" '
                    'data-personal="%s" data-scope="%s" data-pers-name="%s">%s</span>'
                    % (attr(p.body), attr(p.scope), attr(p.name), form_esc))

        # both：同一位置系统 + 个人
        tip = "" if p.hide else t.desc
        cls = "term term-type-%s" % attr(t.type_id)
        if p.hide:
            cls += " term-empty"
        inner = ('<span class="%s" data-tooltip="%s" data-personal="%s" '
                 'data-scope="%s" data-pers-name="%s" data-term="%s">%s</span>'
                 % (cls, attr(tip), attr(p.body), attr(p.scope),
                    attr(p.name), attr(t.name), form_esc))
        if t.link:
            return ('<a href="%s" target="_blank" rel="noopener">%s</a>'
                    % (attr(t.link), inner))
        return inner


# ---------------------------------------------------------------- Markdown -> HTML

def inline(text_esc, matcher):
    """行内元素：术语标记 -> 粗体 -> 斜体 -> 行内代码。输入必须是已转义文本。"""
    text_esc = matcher.highlight(text_esc)
    text_esc = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text_esc)
    text_esc = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<em>\1</em>", text_esc)
    text_esc = re.sub(r"`([^`\n]+?)`", r"<code>\1</code>", text_esc)
    return text_esc


def render_quote(block, matcher, supp_cls):
    """引用块：`> 例[史|哲|经]：…` -> 毛玻璃例子卡；其余 -> blockquote。"""
    if not block:
        return ""
    first = block[0]
    m = re.match(u"^例(?:\\[(史|哲|经)\\])?\\s*[：:]\\s*(.*)$", first)
    if m:
        kind = m.group(1) or ""
        cls = supp_cls.get(kind, "supplement-base")
        body = []
        rest = (m.group(2) or "").strip()
        if rest:
            body.append(rest)
        body.extend(block[1:])
        content = "<br>".join(inline(esc(x), matcher) for x in body if x.strip())
        return ('<div class="supplement-example %s">'
                '<strong>\U0001F4A1 补充例子：</strong><br>%s</div>' % (cls, content))
    content = "<br>".join(inline(esc(x), matcher) for x in block)
    return "<blockquote>%s</blockquote>" % content


_SENT_END = re.compile(u"(?<=[。！？])")


def split_sentences(text):
    """按中文句末标点（。！？）切句，保留标点，丢弃空句。"""
    if not text:
        return []
    parts = _SENT_END.split(text)
    return [p.strip() for p in parts if p.strip()]


def md_to_html(md, matcher, supp_cls, skip_first_h1=True):
    """
    skip_first_h1: 首个标题若是 h1，直接跳过（页面 header 已展示标题，避免重复）。
                   只跳过"第一个标题"，若首标题不是 h1 则一个字都不跳。

    句级分段：每个句子单独成 <p class="sent">，段落最后一句额外带 sent-last，
    由 CSS 区分「句间距」与「段间距」。
    """
    lines = md.splitlines()
    out = []
    para = []
    i = 0
    n = len(lines)
    first_heading_seen = False
    toc = []          # [(锚点 id, 标题文本), ...] 只收集 h2

    def flush_para():
        if not para:
            return
        text = " ".join(x for x in para if x.strip())
        para.clear()
        if not text.strip():
            return
        sents = split_sentences(text)
        if not sents:
            return
        last = len(sents) - 1
        for idx, sent in enumerate(sents):
            cls = "sent sent-last" if idx == last else "sent"
            out.append('<p class="%s">%s</p>' % (cls, inline(esc(sent), matcher)))

    while i < n:
        s = lines[i].strip()

        if not s:
            flush_para()
            i += 1
            continue

        m = re.match(r"^(#{1,6})\s+(.*?)\s*#*$", s)
        if m:
            flush_para()
            lvl = len(m.group(1))
            if skip_first_h1 and not first_heading_seen:
                first_heading_seen = True
                if lvl == 1:
                    # 首个标题是 h1：页面 header 已有书名，跳过
                    i += 1
                    continue
            text = m.group(2)
            if lvl == 2:
                sec_id = "sec-%d" % (len(toc) + 1)
                toc.append((sec_id, text))
                # 标题不参与术语标记（与下游既有规则一致）
                out.append('<h2 id="%s">%s</h2>' % (sec_id, esc(text)))
            else:
                out.append("<h%d>%s</h%d>" % (lvl, esc(text), lvl))
            i += 1
            continue

        if s.startswith(">"):
            flush_para()
            block = []
            while i < n and lines[i].strip().startswith(">"):
                block.append(lines[i].strip()[1:].lstrip())
                i += 1
            out.append(render_quote(block, matcher, supp_cls))
            continue

        if re.match(r"^[-*+]\s+", s):
            flush_para()
            items = []
            while i < n and re.match(r"^[-*+]\s+", lines[i].strip()):
                items.append(lines[i].strip()[2:].strip())
                i += 1
            out.append("<ul>%s</ul>"
                       % "".join("<li>%s</li>" % inline(esc(x), matcher) for x in items))
            continue

        if re.match(r"^\d+[.)]\s+", s):
            flush_para()
            items = []
            while i < n and re.match(r"^\d+[.)]\s+", lines[i].strip()):
                items.append(re.sub(r"^\d+[.)]\s+", "", lines[i].strip()))
                i += 1
            out.append("<ol>%s</ol>"
                       % "".join("<li>%s</li>" % inline(esc(x), matcher) for x in items))
            continue

        para.append(s)
        i += 1

    flush_para()
    return "\n".join(out), toc


def render_toc(toc):
    """侧边目录：只列 h2，带两位序号。"""
    if not toc:
        return ""
    items = "".join(
        '<li><a href="#%s"><span class="toc-num">%02d</span>'
        '<span class="toc-text">%s</span></a></li>'
        % (attr(sid), idx, esc(text))
        for idx, (sid, text) in enumerate(toc, 1)
    )
    return ('<aside class="toc"><div class="toc-title">目录</div>'
            "<ol>%s</ol></aside>" % items)


# ---------------------------------------------------------------- 图谱 Tab

def fmt_time_span(v):
    if v is None:
        return ""
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return ""
    return '<span class="time-format" data-time="%s">--:--</span>' % fv


def glass_card(label, items):
    if not items:
        return ""
    lis = "".join("<li>%s</li>" % esc(x) for x in items)
    return ('<div class="glass-card"><div class="card-label">%s</div>'
            '<ul>%s</ul></div>' % (label, lis))


def render_author_says(items):
    if not items:
        return ""
    out = ['<div class="author-says">']
    for it in items:
        ts = it.get("timestamp")
        head = ""
        if ts is not None:
            try:
                head = ('<span class="time-format author-time" data-time="%s">--:--</span> '
                        % float(ts))
            except (TypeError, ValueError):
                head = ""
        q = it.get("quote")
        qhtml = ('<strong>原文：</strong>\u201c%s\u201d ' % esc(q)) if q else ""
        txt = it.get("text") or ""
        para = esc(txt) if not q else '<span class="paraphrase">转述：%s</span>' % esc(txt)
        out.append('<p class="say">%s%s%s</p>' % (head, qhtml, para))
    out.append("</div>")
    return "".join(out)


def render_subblock(b):
    bid = b.get("id", "")
    fn = b.get("function", "")
    tr = b.get("time_range") or {}
    span = "%s \u2013 %s" % (fmt_time_span(tr.get("start")), fmt_time_span(tr.get("end")))

    out = ['<details class="graph-subblock" data-block="%s">' % attr(bid)]
    out.append('<summary><code>%s</code> \u00b7 %s \u00b7 %s</summary>'
               % (esc(bid), esc(fn), span))
    out.append('<div class="subblock-body">')

    purpose = b.get("purpose")
    if purpose:
        out.append('<blockquote class="purpose">%s</blockquote>' % esc(purpose))

    kps = b.get("key_points") or []
    if kps:
        out.append('<ul class="key-points">%s</ul>'
                   % "".join("<li>%s</li>" % esc(x) for x in kps))

    out.append(render_author_says(b.get("author_says") or []))
    out.append(glass_card("\U0001F9E0 我的推论", b.get("my_inferences")))
    out.append(glass_card("\U0001F4A1 我的例子", b.get("my_examples")))
    out.append(glass_card("\u2753 我的疑问", b.get("my_questions")))

    conf = b.get("confidence")
    if conf:
        out.append('<span class="confidence confidence-%s">置信度：%s</span>'
                   % (attr(conf), esc(conf)))

    out.append("</div></details>")
    return "".join(out)


def render_recap(recap):
    if not recap:
        return ""
    out = ['<section class="graph-block recap">', "<h2>三层复述</h2>"]
    one = recap.get("one_sentence")
    if one:
        out.append('<p class="one-sentence">%s</p>' % esc(one))
    steps = recap.get("main_steps") or []
    if steps:
        out.append("<h3>主要步骤</h3>")
        out.append("<ol>%s</ol>" % "".join("<li>%s</li>" % esc(x) for x in steps))
    qs = recap.get("three_questions") or []
    if qs:
        out.append("<h3>每块三问</h3>")
        for q in qs:
            out.append('<div class="three-q">')
            out.append('<div class="q-block"><code>%s</code></div>' % esc(q.get("block_id", "")))
            out.append('<p><strong>为什么需要：</strong>%s</p>' % esc(q.get("why_needed", "")))
            out.append('<p><strong>依据：</strong>%s</p>' % esc(q.get("basis", "")))
            dep = q.get("depends_on") or []
            if dep:
                out.append('<p><strong>依赖：</strong>%s</p>' % esc("、".join(dep)))
            out.append("</div>")
    out.append("</section>")
    return "".join(out)


def render_graph_tab(analysis):
    sk = analysis.get("skeleton") or {}
    blocks = [b for b in (analysis.get("blocks") or []) if isinstance(b, dict)]
    by_id = {}
    for b in blocks:
        if b.get("id"):
            by_id[b["id"]] = b

    out = ['<div class="graph-header">']
    out.append('<h1 class="core-problem">%s</h1>' % esc(sk.get("core_problem", "")))
    out.append('<p class="core-conclusion">%s</p>' % esc(sk.get("core_conclusion", "")))
    out.append("</div>")

    for sb in (sk.get("blocks") or []):
        sid = sb.get("id", "")
        # P2 补丁后走显式字段；旧数据回退到 id 前缀推断，保证向前兼容
        sub_ids = sb.get("subblock_ids")
        if not sub_ids:
            sub_ids = [b["id"] for b in blocks
                       if isinstance(b.get("id"), str) and b["id"].startswith(sid + "-")]
            if sub_ids:
                log("[warn] %s 缺少 subblock_ids，已回退前缀推断（%d 个）" % (sid, len(sub_ids)))
        out.append('<section class="graph-block">')
        out.append('<h2><span class="fn-tag">[%s]</span> %s</h2>'
                   % (esc(sb.get("function", "")), esc(sb.get("summary", ""))))
        for sub in sub_ids:
            b = by_id.get(sub)
            if b is None:
                out.append('<p class="missing-block">\u26a0 缺少子块数据：%s</p>' % esc(sub))
                continue
            out.append(render_subblock(b))
        out.append("</section>")

    out.append(render_recap(analysis.get("recap") or {}))
    return "\n".join(out)


# ---------------------------------------------------------------- 术语 Tab

def render_terms_tab(terms, counts, marked, personal=None):
    personal = personal or []

    if not terms and not personal:
        return '<p class="empty">本篇未提供术语文件（terms/&lt;id&gt;.md）。</p>'

    # 个人笔记按词条名索引，用于表格里的 📝 标记
    p_by_name = {}
    for p in personal:
        p_by_name.setdefault(p.name, p)

    rows = []
    for t in terms:
        occ = counts.get(t.name, 0)
        mk = marked.get(t.name, 0)
        cls = "term-row" if mk > 0 else "term-row unmatched"
        has_note = "📝" if t.name in p_by_name else ""
        rows.append(
            '<tr class="%s">'
            '<td class="col-name"><span class="term term-type-%s" data-tooltip="%s">%s</span></td>'
            '<td class="col-type">%s</td>'
            '<td class="col-desc">%s</td>'
            '<td class="col-alias">%s</td>'
            '<td class="col-num">%d</td>'
            '<td class="col-num">%d</td>'
            '<td class="col-note">%s</td>'
            "</tr>"
            % (cls, attr(t.type_id), attr(t.desc), esc(t.name),
               esc(t.type_id), esc(t.desc), esc("、".join(t.aliases)), occ, mk, has_note)
        )

    hit = sum(1 for t in terms if marked.get(t.name, 0) > 0)
    head = ('<p class="terms-summary">共 %d 条 · 命中 %d 条 · 未命中 %d 条%s</p>'
            % (len(terms), hit, max(0, len(terms) - hit),
               (" · 我的笔记 %d 条" % len(personal)) if personal else ""))

    table = ""
    if terms:
        table = ('<table class="terms-table"><thead><tr>'
                 "<th>词条</th><th>类型</th><th>解释</th><th>别名</th>"
                 "<th>出现</th><th>标记</th><th>笔记</th></tr></thead><tbody>"
                 + "".join(rows)
                 + "</tbody></table>")

    notes = ""
    if personal:
        cards = []
        for p in personal:
            scope = ('<span class="p-scope">%s</span>' % esc(p.scope)) if p.scope else ""
            hide_tag = '<span class="p-hide">已隐藏系统解释</span>' if p.hide else ""
            body = esc(p.body).replace("\n", "<br>") or '<span class="p-empty">（空白）</span>'
            cards.append(
                '<div class="p-note">'
                '<div class="p-note-head"><span class="p-name">%s</span>%s%s</div>'
                '<div class="p-note-body">%s</div>'
                "</div>" % (esc(p.name), scope, hide_tag, body)
            )
        notes = ('<section class="personal-notes">'
                 '<h3 class="p-title">📝 我的笔记</h3>'
                 + "".join(cards) + "</section>")

    return head + table + notes


def render_feynman_tab(feynman, analysis):
    """
    第四 Tab：费曼练习。
    - 生成只读骨架（问题 + 自评清单）
    - 通过 data-subblock / data-level 给前端 JS 提供作答锚点
    - 顶部工具栏：目标深度 + 保存 + 导出
    """
    if not feynman or not isinstance(feynman, dict):
        return ""
    blocks = feynman.get("blocks") or {}
    if not isinstance(blocks, dict) or not blocks:
        return ""

    max_depth = feynman.get("max_depth") or 3
    by_id = dict((b.get("id"), b) for b in (analysis.get("blocks") or [])
                 if isinstance(b, dict) and b.get("id"))
    sk_blocks = (analysis.get("skeleton") or {}).get("blocks") or []

    out = ['<div class="feynman-wrap">']

    # ---- 工具栏
    depth_opts = "".join(
        '<option value="%d"%s>%d 层</option>'
        % (i, " selected" if i == max_depth else "", i)
        for i in range(1, max_depth + 1)
    )
    out.append('<div class="fe-toolbar" data-max-depth="%d">' % max_depth)
    out.append('<label class="fe-target">目标深度 '
               '<select id="fe-target">%s</select></label>' % depth_opts)
    out.append('<button id="fe-save" type="button">保存练习</button>')
    out.append('<button id="fe-export" type="button">导出 JSON</button>')
    out.append('<span id="fe-status">未保存</span>')
    out.append("</div>")

    out.append('<p class="feynman-intro">按层递进。先看问题自己想一遍，'
               '写下答案后对照自评清单检查漏了什么；标注「完成」表示这一层过关。</p>')

    for sb in sk_blocks:
        ids = [x for x in (sb.get("subblock_ids") or []) if x in blocks]
        if not ids:
            continue
        out.append('<section class="feynman-group">')
        out.append('<h3 class="feynman-group-title">%s</h3>'
                   % esc(sb.get("summary", "")))
        for bid in ids:
            b = by_id.get(bid) or {}
            out.append('<div class="feynman-card" data-subblock="%s">' % attr(bid))
            out.append('<div class="feynman-card-head"><code>%s</code> · %s</div>'
                       % (esc(bid), esc(b.get("function", ""))))
            purpose = (b.get("purpose") or "").strip()
            if purpose:
                out.append('<p class="feynman-purpose">%s</p>' % esc(purpose))

            for ly in blocks[bid]:
                lvl = ly.get("level", "")
                out.append('<div class="feynman-layer" data-level="%s" '
                           'data-name="%s">' % (esc(lvl), attr(ly.get("name", ""))))
                out.append('<div class="feynman-layer-head">L%s · %s</div>'
                           % (esc(lvl), esc(ly.get("name", ""))))
                out.append('<div class="feynman-q">%s</div>'
                           % esc(ly.get("question", "")))
                rub = (ly.get("rubric") or "").strip()
                if rub:
                    items = "".join("<li>%s</li>" % esc(x.strip())
                                    for x in rub.splitlines() if x.strip())
                    # 默认折叠：先自己想，写完再展开对照
                    out.append('<details class="fr">')
                    out.append('<summary class="fr-toggle">自评清单</summary>')
                    out.append('<ul class="feynman-rubric">%s</ul>' % items)
                    out.append("</details>")
                out.append("</div>")

            out.append("</div>")
        out.append("</section>")

    out.append("</div>")
    return "\n".join(out)


# ---------------------------------------------------------------- 样式与模板

def extract_css(themes_md):
    """提取 themes.md 中全部 ```css 代码块并拼接。"""
    blocks = re.findall(r"```css[ \t]*\r?\n(.*?)```", themes_md, re.S | re.I)
    css = "\n\n".join(b.strip() for b in blocks)
    if not css.strip():
        die(5, "themes.md 中未找到 ```css 代码块")
    return css


def rewrite_font_paths(css, build_dir):
    """assets/fonts/... -> 相对输出文件的真实相对路径。"""
    rel = os.path.relpath(str(FONTS), str(build_dir)).replace("\\", "/")
    if not rel.startswith("."):
        rel = "./" + rel
    css = re.sub(r"url\(\s*(['\"])assets/fonts/",
                 lambda m: "url(%s%s/" % (m.group(1), rel), css)
    return css, rel


def fill_template(tpl, values):
    for k, v in values.items():
        tpl = tpl.replace("{{" + k + "}}", str(v))
    return tpl


# ---------------------------------------------------------------- 主流程

def resolve_artifact(pkg, rel):
    """
    产物路径解析（防串包）：
    - `terms/` 开头 -> 仓库根的顶层 terms/（术语是跨包资产）
    - 其他          -> 只允许落在**本包目录内**
    任何逃出允许范围的路径一律返回 None，
    避免 A 包的 deliver.json 解析到 B 包的文件、从而串包渲染。
    """
    rel_posix = str(rel).replace("\\", "/").lstrip("/")

    if rel_posix.startswith("terms/"):
        cand = (ROOT / rel_posix).resolve()
        return cand if cand.is_file() else None

    pkg_res = pkg.resolve()

    # 1) 相对包根（标准写法：analysis/analysis.json）
    cand = (pkg / rel_posix).resolve()
    if cand.is_file() and pkg_res in cand.parents:
        return cand

    # 2) 兼容旧写法：corpus/<本包id>/analysis/...（仍必须落在本包内）
    cand = (ROOT / rel_posix).resolve()
    if cand.is_file() and pkg_res in cand.parents:
        return cand

    return None


def render_one(article_id, force=False, check_only=False):
    pkg = CORPUS / article_id
    deliver_path = pkg / "deliver.json"

    if not deliver_path.is_file():
        log("[skip] %s: deliver.json 不存在（可能尚未发布）" % article_id)
        return 2

    try:
        deliver = load_json(deliver_path)
    except Exception as e:
        die(5, "%s: deliver.json 解析失败: %s" % (article_id, e))

    status = deliver.get("status")
    if status != "ready":
        log("[skip] %s: status=%s（不是 ready，不渲染）" % (article_id, status))
        return 2

    if deliver.get("article_id") and deliver["article_id"] != article_id:
        die(3, "%s: deliver.json 的 article_id 是 %s，与目录名不符（疑似整包复制）。\n"
               "      拒绝渲染 —— 请删除该包并按 publish.py 重新发布。"
            % (article_id, deliver["article_id"]))

    # --- 产物完整性（sha256）
    artifacts = deliver.get("artifacts") or []
    if not artifacts:
        die(3, "%s: deliver.json 未声明任何 artifacts" % article_id)

    resolved = {}
    for a in artifacts:
        kind = a.get("kind")
        rel = a.get("path", "")
        p = resolve_artifact(pkg, rel)
        if p is None:
            die(3, "%s: 产物缺失 %s（%s）" % (article_id, kind, rel))
        actual = sha256_file(p)
        expect = (a.get("sha256") or "").lower()
        if expect and actual != expect:
            die(3, "%s: 产物哈希不匹配 %s\n  期望 %s\n  实际 %s"
                % (article_id, rel, expect, actual))
        resolved[kind] = p

    # --- checks 闸门
    bad = dict((k, v) for k, v in (deliver.get("checks") or {}).items() if v != "pass")
    if bad:
        log("[reject] %s: checks 未通过 %s（拒绝渲染）" % (article_id, bad))
        return 4

    if check_only:
        log("[ok] %s: deliver.json 校验通过（%d 个产物）" % (article_id, len(resolved)))
        return 0

    # --- 输入
    analysis_p = resolved.get("analysis")
    article_p = resolved.get("article_examples") or resolved.get("article")
    terms_p = resolved.get("terms")
    if analysis_p is None:
        die(5, "%s: 缺 analysis 产物" % article_id)
    if article_p is None:
        die(5, "%s: 缺 article / article_examples 产物" % article_id)

    out_dir = pkg / "build"
    out_dir.mkdir(parents=True, exist_ok=True)
    fingerprint_path = out_dir / ".render.json"

    inputs = {
        "deliver": deliver_fingerprint(deliver),
        # 渲染器自身代码也纳入指纹：改了 render.py 就不再误跳过
        "renderer": sha256_file(Path(__file__).resolve()),
    }
    for name, p in (("analysis", analysis_p), ("article", article_p),
                    ("terms", terms_p), ("themes", THEMES), ("template", TEMPLATE)):
        if p is not None:
            inputs[name] = sha256_file(p)

    # 个人术语纳入指纹：改笔记必须触发重渲
    personal_p = PERSONAL_DIR / ("%s.md" % article_id)
    inputs["personal_terms"] = sha256_file(personal_p) if personal_p.is_file() else "absent"

    # 费曼骨架纳入指纹：重跑 pass9 后必须重渲
    feynman_p = pkg / "analysis" / "feynman.json"
    inputs["feynman"] = sha256_file(feynman_p) if feynman_p.is_file() else "absent"

    # --- 幂等
    html_path = out_dir / ("%s.html" % article_id)
    if not force and fingerprint_path.is_file():
        try:
            prev = load_json(fingerprint_path)
        except Exception:
            prev = {}
        if (prev.get("inputs") == inputs
                and prev.get("renderer_version") == RENDERER_VERSION
                and html_path.is_file()):
            log("[skip] %s: 输入未变，跳过渲染（--force 可强制）" % article_id)
            return 0

    # --- 读取样式与模板
    if not THEMES.is_file():
        die(5, "缺少主题文件: %s" % THEMES)
    if not TEMPLATE.is_file():
        die(5, "缺少模板文件: %s" % TEMPLATE)

    enums = load_enums()
    supp_cls = enums.get("supplement_example_class") or {}

    css = extract_css(read_text(THEMES))
    css, font_rel = rewrite_font_paths(css, out_dir)

    # --- 读取数据
    try:
        analysis = load_json(analysis_p)
        article_md = read_text(article_p)
        terms = parse_terms_md(read_text(terms_p), str(terms_p)) if terms_p else []
    except Exception as e:
        die(5, "%s: 输入解析失败: %s" % (article_id, e))

    # --- 个人术语（缺省 / 格式错误一律降级，不拒绝渲染）
    personal = []
    if personal_p.is_file():
        try:
            personal, pwarns = parse_personal_terms(read_text(personal_p),
                                                    str(personal_p.name))
            for w in pwarns:
                log("[personal-warn] " + w)
            if personal:
                log("[personal] %s: 解析到 %d 条个人笔记" % (article_id, len(personal)))
        except Exception as e:
            log("[personal-warn] %s: 个人术语解析失败（%s），降级为仅系统层"
                % (article_id, e))

    # --- 渲染三个 Tab
    matcher = TermMatcher(terms, personal)
    counts = matcher.count(esc(article_md))
    pane_text, toc_items = md_to_html(article_md, matcher, supp_cls)
    toc_html = render_toc(toc_items)
    pane_graph = render_graph_tab(analysis)
    pane_terms = render_terms_tab(terms, counts, matcher.marked, personal)

    # --- 费曼练习（可选：老文章没有骨架就跳过第四 Tab）
    feynman = None
    if feynman_p.is_file():
        try:
            feynman = load_json(feynman_p)
        except Exception as e:
            log("[warn] %s: feynman.json 解析失败（%s），跳过练习区"
                % (article_id, e))
    pane_feynman = render_feynman_tab(feynman, analysis) if feynman else ""
    feynman_blocks = len((feynman or {}).get("blocks") or {}) if feynman else 0

    if matcher.dropped_personal:
        log("[personal-warn] %s: %d 处个人命中与系统术语重叠，按「系统优先」丢弃"
            % (article_id, matcher.dropped_personal))

    title = (deliver.get("title")
             or (analysis.get("meta") or {}).get("title")
             or article_id)

    html_str = fill_template(read_text(TEMPLATE), {
        "TITLE": esc(title),
        "STYLE": css,
        "FONT_REL": font_rel,
        "ARTICLE_ID": esc(article_id),
        "GENERATED_AT": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "PANE_TEXT": pane_text,
        "TOC": toc_html,
        "PANE_GRAPH": pane_graph,
        "PANE_TERMS": pane_terms,
        "PANE_FEYNMAN": pane_feynman,
        "FEYNMAN_COUNT": str(feynman_blocks),
        "SUBBLOCK_COUNT": str(len((analysis.get("blocks") or []))),
        "TERM_COUNT": str(len(terms)),
        "RENDERER_VERSION": RENDERER_VERSION,
    })

    # --- 原子落盘
    tmp_path = out_dir / ("%s.html.tmp" % article_id)
    write_text(tmp_path, html_str)
    os.replace(str(tmp_path), str(html_path))

    # --- 指纹
    outline = {
        "article_id": article_id,
        "rendered_at": datetime.now().isoformat(timespec="seconds"),
        "renderer_version": RENDERER_VERSION,
        "inputs": inputs,
        "output_sha256": sha256_file(html_path),
        "bytes": html_path.stat().st_size,
    }
    write_text(fingerprint_path, json.dumps(outline, ensure_ascii=False, indent=2))

    # --- 匹配报告
    report = {
        "article_id": article_id,
        "terms_total": len(terms),
        "terms_hit": sum(1 for t in terms if matcher.marked.get(t.name, 0) > 0),
        "marked": dict((k, v) for k, v in matcher.marked.items() if v),
        "unmatched": [t.name for t in terms if not matcher.marked.get(t.name, 0)],
        "occurrence": dict((k, v) for k, v in counts.items() if v),
        "forms_hit": dict((k, sorted(v)) for k, v in matcher.forms_seen.items()),
        "personal_total": len(personal),
        "personal_hit": dict((k, v) for k, v in matcher.personal_seen.items()),
        "personal_dropped": matcher.dropped_personal,
        "html_bytes": html_path.stat().st_size,
    }
    write_text(out_dir / ("%s.report.json" % article_id),
               json.dumps(report, ensure_ascii=False, indent=2))

    log("[ok] %s -> %s (%d bytes, %d 术语命中/%d)"
        % (article_id, html_path, html_path.stat().st_size,
           report["terms_hit"], len(terms)))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="文章包合一渲染器（正文 / 图谱 / 术语 三 Tab）")
    ap.add_argument("--id", help="文章 id（corpus/ 下的目录名）")
    ap.add_argument("--all", action="store_true", help="处理 corpus/ 下全部文章包")
    ap.add_argument("--force", action="store_true", help="忽略幂等指纹强制重渲")
    ap.add_argument("--check-only", action="store_true", help="只校验 deliver.json，不渲染")
    args = ap.parse_args(argv)

    try:
        if args.all:
            if not CORPUS.is_dir():
                log("[warn] corpus/ 不存在: %s" % CORPUS)
                return 0
            ids = sorted(p.name for p in CORPUS.iterdir()
                         if p.is_dir() and (p / "deliver.json").is_file())
            if not ids:
                log("[warn] corpus/ 下没有可处理的文章包")
                return 0
            rc = 0
            for aid in ids:
                rc = max(rc, render_one(aid, args.force, args.check_only))
            return rc

        if not args.id:
            ap.error("需要 --id <article_id> 或 --all")
        return render_one(args.id, args.force, args.check_only)

    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
