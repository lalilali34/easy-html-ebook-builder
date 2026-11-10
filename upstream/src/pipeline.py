#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pipeline.py — raw.md → analysis.json / article.md / terms.md
============================================================

方案 B 的精简编排器：只做「纯文本 → 结构化产物」，不带旧 run_pipeline 的
emit-prompt / coverage_report / dry-run 占位分支。

核心能力
--------
1. **超长分块**（任务 2）：raw.md 超过 `--max-chars`（默认 10000 字）时，
   按段落边界切块 → 每块调模型压缩成结构化摘要 → 用压缩稿继续跑后续 pass，
   避免单次请求 Token 溢出。
2. **纯文本时间轴**：txt 没有真实秒数，按段落序号生成等距伪时间轴
   （每段默认 10 秒），保证 analysis.json 的 time_range 合法。
3. **pass1–pass8 编排**：pass1 出 7 大块 → 逐大块跑 pass2 出子块 →
   pass3 关系 → pass4 逐块 → pass5 两阶段 → pass6 复述 →
   pass7/7s 成文 → pass8 术语。
4. **dry-run**：不调模型，用规则生成结构合法的占位产物，写到
   `*.dryrun.*`，**不覆盖正式文件**，用于无 Key 时验证管线。

用法：
    python upstream/src/pipeline.py --id 20261109_bourgeois
    python upstream/src/pipeline.py --id 20261109_bourgeois --dry-run
    python upstream/src/pipeline.py --id 20261109_bourgeois --max-chars 8000

退出码：
    0  成功
    3  缺 raw.md
    4  产物校验未通过
    5  调用/解析失败
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "corpus"
PROMPTS = ROOT / "upstream" / "prompts"

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from llm_client import LLMClient, LLMError  # noqa: E402

DEFAULT_MAX_CHARS = 24000
SEG_STEP = 10.0

PASS_FILES = {
    "pass0": "pass0_asr_fix.md",
    "pass1": "pass1_skeleton.md",
    "pass2": "pass2_function_blocks.md",
    "pass3": "pass3_relations.md",
    "pass4": "pass4_block_analysis.md",
    "pass5": "pass5_attribution.md",
    "pass6": "pass6_recap.md",
    "pass7": "pass7_article.md",
    "pass7s": "pass7s_article_with_examples.md",
    "pass7e": "pass7e_examples.md",
    "pass8": "pass8_terms.md",
    "pass9": "pass9_feynman.md",
}

# 输出 Markdown 而非 JSON 的轮次
TEXT_PASSES = ("pass7", "pass7s", "pass7e", "pass8")

# 费曼五层（固定，与 prompts/pass9_feynman.md 一致）
FEYNMAN_LAYERS = [
    (1, "复述"),
    (2, "论证重构"),
    (3, "举例/边界"),
    (4, "连接"),
    (5, "批判"),
]
FEYNMAN_BATCH_SIZE = 4

CONDENSE_SYSTEM = """你是严谨的文本压缩器。把给定片段压缩成结构化摘要，规则：
1. 保留全部论点、定义、人名、书名、年份、关键术语与它们的原始写法；
2. 删除重复、口语语气词、寒暄、与论证无关的细节；
3. 保持原文的论证顺序，不重排；
4. 输出纯文本，长度控制在原文的 30%-40%；
5. 不得添加原文没有的判断，不得把推断写成作者的观点。"""

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


def read_text(p):
    with open(str(p), "r", encoding="utf-8-sig", errors="strict") as f:
        return f.read().replace("\r\n", "\n")


def write_text(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(str(p), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def write_json(p, obj):
    write_text(p, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


# ---------------------------------------------------------------- 文本切分

def split_paragraphs(text):
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def split_chunks(text, max_chars=DEFAULT_MAX_CHARS):
    """
    按段落边界切块，**尽量均衡**，单块不超过 max_chars。

    旧实现是贪心装箱，会出现 9527 + 1362 这种尾巴。现在先算最少块数 n，
    以 total/n 为目标逐段累加，达到目标就收块；同时保留 max_chars 硬上限。
    """
    paras = split_paragraphs(text)
    if not paras:
        return [text]

    # 单段超长先硬切，保证后续每段都不超过上限
    normalized = []
    for p in paras:
        if len(p) > max_chars:
            for i in range(0, len(p), max_chars):
                normalized.append(p[i:i + max_chars])
        else:
            normalized.append(p)

    total = sum(len(p) for p in normalized)
    if total <= max_chars:
        return ["\n\n".join(normalized)]

    n = max(2, (total + max_chars - 1) // max_chars)   # 最少需要几块
    target = total / float(n)                          # 每块目标字数

    chunks, cur, size = [], [], 0
    for p in normalized:
        # 硬上限保护：再加就超了，先收块
        if cur and size + len(p) > max_chars:
            chunks.append("\n\n".join(cur))
            cur, size = [], 0

        cur.append(p)
        size += len(p)

        # 达到均衡目标且还能继续切，就收块
        if size >= target and len(chunks) < n - 1:
            chunks.append("\n\n".join(cur))
            cur, size = [], 0

    if cur:
        chunks.append("\n\n".join(cur))
    return chunks or [text]


def extract_title(text):
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        # 跳过 --- / *** / ___ 这类分隔线
        if set(s) <= set("-*_ ") and len(set(s)) <= 2:
            continue
        # 首行过长说明是正文而非标题，放弃
        if len(s) <= 60:
            return s
        break
    return "未命名"


def strip_title(text, title):
    """去掉首行 # 标题，返回正文。"""
    lines = text.splitlines()
    out, dropped = [], False
    for line in lines:
        s = line.strip()
        if not dropped and s and s.lstrip("#").strip() == title:
            dropped = True
            continue
        out.append(line)
    return "\n".join(out).strip("\n")


def build_segments(body, step=SEG_STEP):
    """纯文本 → 伪时间轴 segments。每段 step 秒。"""
    segs = []
    for i, p in enumerate(split_paragraphs(body)):
        segs.append({
            "start": round(i * step, 1),
            "end": round((i + 1) * step, 1),
            "text": p,
        })
    return segs


def segs_in_range(segments, start, end):
    out = [s for s in segments if start <= s["start"] < end]
    return out or segments


# ---------------------------------------------------------------- 模型调用

def load_agent_prompt():
    p = PROMPTS / "agent.md"
    return read_text(p) if p.is_file() else ""


def load_pass_prompt(key):
    p = PROMPTS / PASS_FILES[key]
    if not p.is_file():
        raise LLMError("缺少提示词文件：%s" % p)
    return read_text(p)


def call_json(client, agent_md, key, payload):
    system = agent_md + "\n\n---\n\n" + load_pass_prompt(key)
    user = "输入数据（JSON）：\n\n" + json.dumps(payload, ensure_ascii=False, indent=2)
    return client.chat_json(system, user)


def call_text(client, agent_md, key, payload):
    system = agent_md + "\n\n---\n\n" + load_pass_prompt(key)
    user = "输入数据（JSON）：\n\n" + json.dumps(payload, ensure_ascii=False, indent=2)
    return client.chat(system, user)


# ---------------------------------------------------------------- 容错归一化
# 模型返回的结构会漂移（dict/list 互换、多包一层），这里统一成期望形状，
# 避免一个 pass 返回 list 就把整条流水线打崩。

def as_list(raw, key):
    """尽力从返回值里取出列表。"""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        v = raw.get(key)
        if isinstance(v, list):
            return v
        for v in raw.values():
            if isinstance(v, list):
                return v
    return []


def as_dict(raw, key):
    """尽力从返回值里取出字典（若外层包了 key 就拆一层）。"""
    if isinstance(raw, dict):
        v = raw.get(key)
        if isinstance(v, dict):
            return v
        return raw
    return {}


def normalize_by_block(raw, valid_ids):
    """统一成 {block_id: [items...]}。"""
    out = {}

    def absorb(node):
        if isinstance(node, dict):
            bkeys = [k for k in node if isinstance(k, str) and k in valid_ids]
            if bkeys:
                for k in bkeys:
                    v = node[k]
                    out[k] = list(v) if isinstance(v, list) else [v]
                return
            bid = node.get("block_id") or node.get("blockId")
            if isinstance(bid, str) and bid in valid_ids:
                items = node.get("author_says")
                if isinstance(items, list):
                    out.setdefault(bid, []).extend(items)
                else:
                    out.setdefault(bid, []).append(node)
                return
            for v in node.values():
                absorb(v)
        elif isinstance(node, list):
            for v in node:
                absorb(v)

    absorb(raw)
    return out


def normalize_my_layer(raw, valid_ids):
    """统一成 {block_id: {my_inferences, my_examples, my_questions}}。"""
    out = {}

    def absorb(node):
        if isinstance(node, dict):
            bkeys = [k for k in node if isinstance(k, str) and k in valid_ids]
            if bkeys:
                for k in bkeys:
                    v = node[k]
                    if isinstance(v, dict):
                        out[k] = v
                return
            bid = node.get("block_id") or node.get("blockId")
            if isinstance(bid, str) and bid in valid_ids:
                out[bid] = node
                return
            for v in node.values():
                absorb(v)
        elif isinstance(node, list):
            for v in node:
                absorb(v)

    absorb(raw)
    return out


def call_json_cached(client, agent_md, key, payload, cache_dir,
                     resume=False, tag=None):
    """
    调用 pass 并把**原始响应**落盘到 analysis/pass.<tag>.json。
    resume=True 且缓存存在时直接复用 —— 失败重跑不用重烧前面的 token。
    """
    name = "pass.%s.json" % (tag or key)
    cache = cache_dir / name

    if resume and cache.is_file():
        try:
            log("  [resume] 复用 %s" % name)
            return json.loads(read_text(cache))
        except Exception as e:
            log("  [warn] 缓存 %s 损坏（%s），重新调用" % (name, e))

    raw = call_json(client, agent_md, key, payload)
    try:
        write_json(cache, raw)
    except Exception as e:
        log("  [warn] 写入 %s 失败：%s" % (name, e))
    return raw


# ---------------------------------------------------------------- 压缩

def condense_chunks(chunks, client):
    """逐块压缩，返回压缩后的全文。单块直接返回原文。"""
    if len(chunks) <= 1:
        return chunks[0], []
    parts = []
    for i, ch in enumerate(chunks):
        log("  [condense] 块 %d/%d（%d 字）" % (i + 1, len(chunks), len(ch)))
        parts.append(client.chat(CONDENSE_SYSTEM, ch).strip())
    return "\n\n".join(parts), parts


# ---------------------------------------------------------------- ASR 纠错（pass0）

def run_pass0_asr(article_id, body, client, agent_md, resume=False):
    """
    识别 ASR 错字，只应用 confidence=high 的修正。
    返回 (fixed_body, corrections, applied)。
    全部对照（含未应用的）写入 analysis/asr_fixes.json 供人工复核。
    """
    pkg = CORPUS / article_id
    cache_dir = pkg / "analysis"

    raw = call_json_cached(client, agent_md, "pass0",
                           {"text": body}, cache_dir, resume, tag="0")
    corrections = as_list(raw, "corrections")

    fixed = body
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
        if wrong not in fixed:
            continue
        fixed = fixed.replace(wrong, right)
        applied.append(c)

    write_json(cache_dir / "asr_fixes.json", {
        "corrections": corrections,
        "applied": applied,
        "applied_count": len(applied),
    })
    return fixed, corrections, applied


# ---------------------------------------------------------------- 费曼（pass9）

def build_global_summary(analysis):
    """pass9 每批都要附带的全局上下文，供 L4 指认真实的跨块关系。"""
    sk = analysis.get("skeleton") or {}
    blocks = [b for b in (analysis.get("blocks") or []) if isinstance(b, dict)]
    return {
        "core_problem": sk.get("core_problem", ""),
        "core_conclusion": sk.get("core_conclusion", ""),
        "skeleton": [
            {"id": b.get("id"), "summary": (b.get("summary") or "")[:60]}
            for b in (sk.get("blocks") or []) if isinstance(b, dict)
        ],
        "all_subblocks": [
            {"id": b.get("id"),
             "function": b.get("function", ""),
             "summary": (b.get("purpose") or b.get("basis") or "")[:40]}
            for b in blocks if b.get("id")
        ],
    }


def batch_subblocks(analysis, size=FEYNMAN_BATCH_SIZE):
    """按大块分组切批，每批不超过 size 个子块；未被覆盖的块单独成批。"""
    sk_blocks = ((analysis.get("skeleton") or {}).get("blocks")) or []
    known = set(b.get("id") for b in (analysis.get("blocks") or [])
                if isinstance(b, dict) and b.get("id"))

    batches = []
    for sb in sk_blocks:
        if not isinstance(sb, dict):
            continue
        ids = [x for x in (sb.get("subblock_ids") or []) if x in known]
        for i in range(0, len(ids), size):
            batches.append(ids[i:i + size])

    covered = set(x for b in batches for x in b)
    orphans = sorted(known - covered)
    for i in range(0, len(orphans), size):
        batches.append(orphans[i:i + size])

    return [b for b in batches if b]


def run_pass9(article_id, analysis, client, agent_md, depth=3, resume=False):
    """
    生成费曼骨架并写 analysis/feynman.json。
    返回 {"max_depth": n, "blocks": {subblock_id: [layers...]}}。
    """
    pkg = CORPUS / article_id
    cache_dir = pkg / "analysis"
    by_id = dict((b.get("id"), b) for b in (analysis.get("blocks") or [])
                 if isinstance(b, dict) and b.get("id"))

    global_summary = build_global_summary(analysis)
    batches = batch_subblocks(analysis)
    if not batches:
        raise RuntimeError("没有可生成练习的子块")

    log("[pass9] 费曼骨架：%d 批，深度 %d" % (len(batches), depth))

    result = {}
    for idx, batch in enumerate(batches, 1):
        payload = {
            "global": global_summary,
            "batch": batch,
            "batch_blocks": [by_id[i] for i in batch if i in by_id],
            "depth": depth,
        }
        log("  [pass9] 批 %d/%d：%s" % (idx, len(batches), ", ".join(batch)))
        cache_file = cache_dir / ("pass.9_%d.json" % idx)

        # --resume：缓存里返回子块不足的批次判为无效，强制重跑
        use_cache = False
        if resume and cache_file.is_file():
            try:
                cached = json.loads(read_text(cache_file))
                cached_blocks = as_dict(cached, "blocks")
                if all(isinstance(cached_blocks.get(b), list) for b in batch):
                    use_cache = True
                else:
                    log("  [resume] 批 %d 缓存不完整，重跑" % idx)
            except Exception:
                log("  [resume] 批 %d 缓存损坏，重跑" % idx)

        # 批内返回子块数不足时自动重试一次
        raw = None
        for attempt in (1, 2):
            raw = call_json_cached(client, agent_md, "pass9", payload,
                                   cache_dir, use_cache and attempt == 1,
                                   tag="9_%d" % idx)
            got = [b for b in batch
                   if isinstance(as_dict(raw, "blocks").get(b), list)]
            if len(got) >= len(batch):
                break
            if attempt == 1:
                log("  [pass9-warn] 批 %d 只返回 %d/%d，重试一次"
                    % (idx, len(got), len(batch)))
            else:
                lack = [b for b in batch if b not in got]
                log("  [pass9-warn] 批 %d 重试后仍缺：%s"
                    % (idx, ", ".join(lack)))

        blocks_out = as_dict(raw, "blocks")
        for bid, layers in blocks_out.items():
            if bid not in batch or not isinstance(layers, list):
                continue
            clean = []
            for ly in layers:
                if not isinstance(ly, dict):
                    continue
                lvl = ly.get("level")
                if not isinstance(lvl, int) or lvl < 1 or lvl > depth:
                    continue
                q = (ly.get("question") or "").strip()
                r = (ly.get("rubric") or "").strip()
                if not q or not r:
                    continue
                name = ly.get("name") or dict(FEYNMAN_LAYERS).get(lvl, "")
                clean.append({"level": lvl, "name": name,
                              "question": q, "rubric": r})
            clean.sort(key=lambda x: x["level"])
            if clean:
                result[bid] = clean[:depth]

        missing = [x for x in batch if x not in result]
        if missing:
            log("  [pass9-warn] 批 %d 未返回子块：%s" % (idx, ", ".join(missing)))

    feynman = {"max_depth": depth, "blocks": result}
    write_json(cache_dir / "feynman.json", feynman)
    log("[pass9] 完成：%d 个子块有练习" % len(result))
    return feynman


# ---------------------------------------------------------------- dry-run 占位

def dry_run_analysis(article_id, title, body, max_blocks=7):
    """规则生成结构合法的占位 analysis（明确标记 dry-run，不可用于生产）。"""
    paras = split_paragraphs(body)
    if not paras:
        paras = [body.strip() or "（空文本）"]

    n = max(1, min(max_blocks, len(paras)))
    per = max(1, len(paras) // n)
    groups = [paras[i * per:(i + 1) * per] for i in range(n)]
    groups = [g for g in groups if g]
    if len(groups) < n:
        n = len(groups)

    skeleton_blocks = []
    blocks = []
    relations = []
    questions = []

    for i, g in enumerate(groups, 1):
        bid = "b%d" % i
        start = round((i - 1) * 10 * per, 1)
        end = round(i * 10 * per, 1)
        skeleton_blocks.append({
            "id": bid,
            "time_range": {"start": start, "end": end},
            "function": "主张",
            "summary": "[dry-run] 第 %d 部分占位摘要" % i,
            "subblock_ids": ["%s-1" % bid],
        })
        blocks.append({
            "id": "%s-1" % bid,
            "function": "主张",
            "time_range": {"start": start, "end": end},
            "purpose": "[dry-run] 占位：这一块在全文中的作用",
            "basis": "[dry-run] 占位：依据",
            "depends_on": [],
            "key_points": ["[dry-run] 占位关键点"],
            "author_says": [{
                "text": "[dry-run] 占位转述",
                "quote": g[0][:60],
                "timestamp": start,
            }],
            "my_inferences": [],
            "my_examples": [],
            "my_questions": [],
            "confidence": "low",
        })
        questions.append({
            "block_id": "%s-1" % bid,
            "why_needed": "[dry-run] 占位",
            "basis": "[dry-run] 占位",
            "depends_on": [],
        })
        if i > 1:
            relations.append({
                "from": "b%d-1" % (i - 1),
                "to": "%s-1" % bid,
                "type": "因此",
            })

    return {
        "schema_version": "1.0",
        "meta": {
            "article_id": article_id,
            "title": "[dry-run] " + title,
            "source": article_id,
            "duration": float(len(groups) * 10 * per),
            "chapters": [],
        },
        "skeleton": {
            "core_problem": "[dry-run] 占位核心问题",
            "core_conclusion": "[dry-run] 占位核心结论",
            "blocks": skeleton_blocks,
        },
        "relations": relations,
        "blocks": blocks,
        "recap": {
            "one_sentence": "[dry-run] 占位一句话总结",
            "main_steps": ["[dry-run] 步骤一", "[dry-run] 步骤二"],
            "three_questions": questions,
        },
    }


# ---------------------------------------------------------------- 主流程

def run(article_id, dry_run=False, max_chars=DEFAULT_MAX_CHARS, client=None,
        resume=False, feynman_depth=3, asr_fix=True, force_asr=False):
    pkg = CORPUS / article_id
    raw_p = pkg / "source" / "raw.md"
    if not raw_p.is_file():
        fail("%s: 缺少 source/raw.md（先用 inbox_ingest.py 入库）" % article_id)
        return 3

    raw = read_text(raw_p)
    title = extract_title(raw)
    body = strip_title(raw, title)

    log("[article] %s" % article_id)
    log("[title  ] %s" % title)
    log("[length ] %d 字符" % len(body))

    # ---- 0. pass0：ASR 纠错（只应用 high 置信度）
    # 入库标记 is_subtitle=false 时自动跳过；--no-asr-fix 强制关闭；--asr-fix 强制开启
    do_asr = asr_fix and not dry_run and client is not None
    if do_asr and not force_asr:
        try:
            meta = json.loads(read_text(pkg / "source" / "ingest.json"))
            if meta.get("is_subtitle") is False:
                log("[pass0] 入库标记为非字幕稿，跳过 ASR 纠错（--asr-fix 可强制）")
                do_asr = False
        except Exception:
            pass      # 没有标记时按默认跑

    if do_asr:
        log("[pass0] 检测 ASR 错字 …")
        try:
            fixed, corrections, applied = run_pass0_asr(
                article_id, body, client, load_agent_prompt(), resume)
            if applied:
                log("[pass0] 发现 %d 条，自动应用 %d 条："
                    % (len(corrections), len(applied)))
                for c in applied[:8]:
                    log("        %s -> %s" % (c.get("wrong"), c.get("right")))
                if len(applied) > 8:
                    log("        … 另有 %d 条" % (len(applied) - 8))
                body = fixed
                write_text(pkg / "source" / "raw.fixed.md",
                           "# " + title + "\n\n" + body + "\n")
            elif corrections:
                log("[pass0] 发现 %d 条可疑，均未自动应用（见 analysis/asr_fixes.json）"
                    % len(corrections))
            else:
                log("[pass0] 未发现明显 ASR 错字")
        except Exception as e:
            log("[warn] pass0 失败，用原文继续：%s" % e)

    chunks = split_chunks(body, max_chars)
    log("[chunks ] %d 块（阈值 %d 字）" % (len(chunks), max_chars))

    suffix = ".dryrun" if dry_run else ""

    if dry_run:
        analysis = dry_run_analysis(article_id, title, body)
        out_dir = pkg / "analysis"
        json_path = out_dir / ("analysis%s.json" % suffix)
        write_json(json_path, analysis)
        log("[dry-run] 已写出 %s" % json_path.name)

        text_dir = pkg / "text"
        art = "# %s\n\n%s\n" % (title, body)
        write_text(text_dir / ("article%s.md" % suffix), art)
        write_text(text_dir / ("article_with_examples%s.md" % suffix), art)
        log("[dry-run] 已写出 text/article%s.md" % suffix)
        return 0

    if client is None:
        client = LLMClient()
    if not client.available():
        fail("未配置 LLM API Key。见 .env.example；或无 Key 时用 --dry-run 验证管线。")
        return 5

    agent_md = load_agent_prompt()

    # ---- 0. 超长压缩（任务 2）
    if len(chunks) > 1:
        log("[condense] 超过 %d 字，进入分块压缩" % max_chars)
        work, _ = condense_chunks(chunks, client)
        log("[condense] 压缩后 %d 字" % len(work))
    else:
        work = body

    segments = build_segments(work)
    log("[segments] %d 段伪时间轴" % len(segments))

    meta = {
        "article_id": article_id,
        "title": title,
        "source": article_id,
        "duration": round(len(segments) * SEG_STEP, 1),
        "chapters": [],
    }

    # ---- 1. pass1 骨架
    log("[pass1] 生成骨架 …")
    p1 = call_json_cached(client, agent_md, "pass1",
                          {"meta": meta, "segments": segments},
                          pkg / "analysis", resume, tag="1")
    p1d = as_dict(p1, "skeleton")
    sk_blocks = as_list(p1, "blocks")
    if not sk_blocks:
        fail("pass1 未产出任何大块")
        return 5

    # ---- 2. pass2 逐大块出子块
    log("[pass2] 逐大块生成子块（%d 块）…" % len(sk_blocks))
    subblocks = []
    for sb in sk_blocks:
        tr = sb.get("time_range") or {}
        segs = segs_in_range(segments, tr.get("start", 0), tr.get("end", 1e9))
        r = call_json_cached(client, agent_md, "pass2",
                             {"segments": segs, "skeleton": p1},
                             pkg / "analysis", resume, tag="2_%s" % sb.get("id"))
        for k, blk in enumerate(as_list(r, "blocks"), 1):
            if not isinstance(blk, dict):
                continue
            blk = dict(blk)
            blk["id"] = "%s-%d" % (sb.get("id"), k)
            subblocks.append(blk)
        sb["subblock_ids"] = [b["id"] for b in subblocks
                              if str(b["id"]).startswith(str(sb.get("id")) + "-")]
    if not subblocks:
        fail("pass2 未产出任何子块")
        return 5
    log("[pass2] 共 %d 个子块" % len(subblocks))

    # ---- 3. pass3 关系
    log("[pass3] 推断块间关系 …")
    p3 = call_json_cached(client, agent_md, "pass3", {"blocks": subblocks},
                          pkg / "analysis", resume, tag="3")
    relations = as_list(p3, "relations")

    # ---- 4. pass4 逐块分析
    log("[pass4] 逐块分析（%d 块）…" % len(subblocks))
    p4 = call_json_cached(client, agent_md, "pass4", {
        "blocks": subblocks,
        "relations": relations,
        "segments": segments,
    }, pkg / "analysis", resume, tag="4")
    p4_map = dict((b.get("id"), b) for b in as_list(p4, "blocks")
                  if isinstance(b, dict) and b.get("id"))

    merged = []
    for sb in subblocks:
        extra = p4_map.get(sb.get("id")) or {}
        merged.append({
            "id": sb.get("id"),
            "function": sb.get("function"),
            "time_range": sb.get("time_range"),
            "purpose": extra.get("purpose") or "[缺失]",
            "basis": extra.get("basis") or "[缺失]",
            "depends_on": extra.get("depends_on") or [],
            "key_points": extra.get("key_points") or [],
            "author_says": [],
            "my_inferences": [],
            "my_examples": [],
            "my_questions": [],
            "confidence": extra.get("confidence") or "medium",
        })

    # ---- 5. pass5 两阶段
    log("[pass5] 阶段 A：author_says …")
    valid_ids = [b["id"] for b in merged]

    p5a = call_json_cached(client, agent_md, "pass5",
                           {"blocks": merged, "segments": segments, "stage": "A"},
                           pkg / "analysis", resume, tag="5a")
    says = normalize_by_block(p5a, valid_ids)

    log("[pass5] 阶段 B：my_* …")
    p5b = call_json_cached(client, agent_md, "pass5", {
        "blocks": merged,
        "segments": segments,
        "confirmed_author_says": says,
        "stage": "B",
    }, pkg / "analysis", resume, tag="5b")
    my_layer = normalize_my_layer(p5b, valid_ids)

    for b in merged:
        bid = b["id"]
        b["author_says"] = says.get(bid) or []
        layer = my_layer.get(bid) or {}
        b["my_inferences"] = layer.get("my_inferences") or []
        b["my_examples"] = layer.get("my_examples") or []
        b["my_questions"] = layer.get("my_questions") or []

    # ---- 6. pass6 复述
    log("[pass6] 生成复述 …")
    p6 = call_json_cached(client, agent_md, "pass6", {
        "skeleton": p1,
        "blocks": merged,
        "relations": relations,
    }, pkg / "analysis", resume, tag="6")
    p6d = as_dict(p6, "recap")

    analysis = {
        "schema_version": "1.0",
        "meta": meta,
        "skeleton": {
            "core_problem": p1d.get("core_problem") or "[缺失]",
            "core_conclusion": p1d.get("core_conclusion") or "[缺失]",
            "blocks": sk_blocks,
        },
        "relations": relations,
        "blocks": merged,
        "recap": {
            "one_sentence": p6d.get("one_sentence") or "[缺失]",
            "main_steps": p6d.get("main_steps") or ["[缺失]"],
            "three_questions": p6d.get("three_questions") or [],
        },
    }

    # ---- 7. 落盘 analysis
    out_dir = pkg / "analysis"
    json_path = out_dir / ("analysis%s.json" % suffix)
    write_json(json_path, analysis)
    log("[write] %s" % json_path)

    # ---- 8. pass7 成文
    text_dir = pkg / "text"
    log("[pass7] 正文成文 …")
    article_md = call_text(client, agent_md, "pass7", {
        "skeleton": analysis["skeleton"],
        "blocks": merged,
        "relations": relations,
    })
    write_text(text_dir / ("article%s.md" % suffix), article_md.strip() + "\n")
    log("[write] text/article%s.md" % suffix)

    # ---- 9. pass7s 补充例子
    log("[pass7s] 生成带例子的正文 …")
    with_examples = call_text(client, agent_md, "pass7s", {
        "article_md": article_md,
        "blocks": merged,
    })
    write_text(text_dir / ("article_with_examples%s.md" % suffix),
               with_examples.strip() + "\n")
    log("[write] text/article_with_examples%s.md" % suffix)

    # ---- 10. pass8 术语
    log("[pass8] 抽取术语 …")
    terms_md = call_text(client, agent_md, "pass8", {
        "blocks": merged,
        "article_md": article_md,
    })
    terms_path = ROOT / "terms" / ("%s.md" % article_id)
    write_text(terms_path, terms_md.strip() + "\n")
    log("[write] terms/%s.md" % article_id)

    # ---- 11. pass9 费曼骨架（失败不阻断主流程）
    if feynman_depth and feynman_depth > 0:
        log("[pass9] 生成费曼练习骨架 …")
        try:
            run_pass9(article_id, analysis, client, agent_md,
                      depth=feynman_depth, resume=resume)
        except Exception as e:
            log("[warn] pass9 失败，跳过费曼骨架：%s" % e)

    # ---- 12. 校验
    try:
        import validate as _validate
        ok, errs, warns = _validate.validate_analysis(
            analysis, expected_article_id=article_id)
        for w in warns:
            log("[schema-warn] " + w)
        for e in errs[:20]:
            log("[schema] " + e)
        if not ok:
            log("[FAIL] 产物未通过严格校验（仍已落盘，便于排查）")
            return 4
        log("[validate] schema + 语义校验通过")
    except SystemExit as e:
        fail(str(e))
        return 5

    log("[ok] %s 流水线完成" % article_id)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="raw.md → analysis/article/terms 编排器")
    ap.add_argument("--id", required=True, help="文章 id（corpus/ 下的目录名）")
    ap.add_argument("--dry-run", action="store_true",
                    help="不调模型，生成 *.dryrun.* 占位产物")
    ap.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                    help="超过该字数启用分块压缩（默认 10000）")
    ap.add_argument("--resume", action="store_true",
                    help="复用 analysis/pass.*.json 里已保存的 pass 原始响应，只重跑缺失部分")
    ap.add_argument("--feynman-depth", type=int, default=3, choices=[0, 1, 2, 3, 4, 5],
                    help="费曼练习生成到第几层（0=不生成，默认 3）")
    ap.add_argument("--no-asr-fix", action="store_true",
                    help="跳过 pass0 的 ASR 错字修正")
    ap.add_argument("--asr-fix", action="store_true",
                    help="强制跑 pass0，忽略入库标记 is_subtitle=false")
    args = ap.parse_args(argv)

    try:
        client = None if args.dry_run else LLMClient()
        if client is not None:
            log("[llm] " + client.describe())
        return run(args.id, args.dry_run, args.max_chars, client,
                   args.resume, args.feynman_depth,
                   not args.no_asr_fix, args.asr_fix)
    except LLMError as e:
        fail(str(e))
        return 5
    except KeyboardInterrupt:
        fail("已中断")
        return 130


if __name__ == "__main__":
    sys.exit(main())
