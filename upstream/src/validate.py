#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate.py — analysis.json 严格校验器（零第三方依赖）
=====================================================

两层校验：

1. **Schema 层**：按 contract/analysis.schema.json 做 draft-07 子集校验
   （type / enum / const / pattern / minLength / minItems / maxItems /
    minimum / required / properties / additionalProperties / items /
    anyOf / 本地 $ref）。不依赖 jsonschema，装了也会优先用不上的那套逻辑，
   保证任何机器结果一致。

2. **语义层**：schema 表达不了的规则——
   - skeleton.blocks[].subblock_ids 与 blocks[] 必须一一闭环
   - subblock_ids 里的 id 必须归属对应大块（b1-* 只能挂在 b1 下）
   - depends_on / relations / three_questions 只能指向已存在的块
   - three_questions 数量必须等于 blocks 数量
   - meta.article_id 必须等于包目录名
   - contract/enums.json 与 schema 内联枚举不得漂移（P6）

用法：
    python upstream/src/validate.py <analysis.json> [--id 20261109_bourgeois]
    python upstream/src/validate.py corpus/*/analysis/analysis.json --all

退出码：
    0  全部通过
    1  存在校验错误
    5  文件/契约读取失败
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "contract" / "analysis.schema.json"
ENUMS_PATH = ROOT / "contract" / "enums.json"

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

_schema_cache = {}
_enums_cache = {}


def log(msg):
    print(msg, flush=True)


def fail(msg):
    print("[FAIL] " + str(msg), file=sys.stderr, flush=True)


def read_json(path):
    with open(str(path), "r", encoding="utf-8-sig", errors="strict") as f:
        return json.loads(f.read())


def load_schema():
    if "schema" not in _schema_cache:
        if not SCHEMA_PATH.is_file():
            raise SystemExit("[FAIL] 缺少 schema: %s" % SCHEMA_PATH)
        _schema_cache["schema"] = read_json(SCHEMA_PATH)
    return _schema_cache["schema"]


def load_enums():
    if "enums" not in _enums_cache:
        if not ENUMS_PATH.is_file():
            raise SystemExit("[FAIL] 缺少 enums: %s" % ENUMS_PATH)
        _enums_cache["enums"] = read_json(ENUMS_PATH)
    return _enums_cache["enums"]


# ---------------------------------------------------------------- Schema 层

def _type_ok(inst, t):
    if t == "object":
        return isinstance(inst, dict)
    if t == "array":
        return isinstance(inst, list)
    if t == "string":
        return isinstance(inst, str)
    if t == "number":
        return isinstance(inst, (int, float)) and not isinstance(inst, bool)
    if t == "integer":
        return isinstance(inst, int) and not isinstance(inst, bool)
    if t == "boolean":
        return isinstance(inst, bool)
    if t == "null":
        return inst is None
    return True


def _resolve(root, ref):
    if not ref.startswith("#/"):
        raise ValueError("只支持本地 $ref: %s" % ref)
    node = root
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            raise ValueError("无法解析 $ref: %s" % ref)
        node = node[part]
    return node


def check(inst, sch, root, path, errs):
    """draft-07 子集校验，错误追加到 errs（形如 `$.a.b[3].c: ...`）。"""
    if sch is True or sch is None:
        return
    if sch is False:
        errs.append("%s: 此处不允许出现任何值" % path)
        return
    if not isinstance(sch, dict):
        return

    if "$ref" in sch:
        check(inst, _resolve(root, sch["$ref"]), root, path, errs)
        return

    if "anyOf" in sch:
        branches = sch["anyOf"]
        passed = False
        for sub in branches:
            sub_errs = []
            check(inst, sub, root, path, sub_errs)
            if not sub_errs:
                passed = True
                break
        if not passed:
            errs.append("%s: 不满足 anyOf 的任何一个分支（%d 个分支均失败）"
                        % (path, len(branches)))
        # anyOf 之外的兄弟关键字继续校验

    t = sch.get("type")
    if t is not None and not _type_ok(inst, t):
        errs.append("%s: 类型应为 %s，实际 %s" % (path, t, type(inst).__name__))
        return

    if "const" in sch and inst != sch["const"]:
        errs.append("%s: 必须等于 %r" % (path, sch["const"]))

    if "enum" in sch and inst not in sch["enum"]:
        preview = sch["enum"][:10]
        errs.append("%s: 取值 %r 不在允许集合 %s%s"
                    % (path, inst, preview, "…" if len(sch["enum"]) > 10 else ""))

    if isinstance(inst, str):
        if "pattern" in sch and not re.search(sch["pattern"], inst):
            errs.append("%s: 不匹配 %s（值 %r）" % (path, sch["pattern"], inst[:60]))
        if "minLength" in sch and len(inst) < sch["minLength"]:
            errs.append("%s: 长度 %d < %d" % (path, len(inst), sch["minLength"]))

    if isinstance(inst, (int, float)) and not isinstance(inst, bool):
        if "minimum" in sch and inst < sch["minimum"]:
            errs.append("%s: %r < minimum %r" % (path, inst, sch["minimum"]))

    if isinstance(inst, list):
        if "minItems" in sch and len(inst) < sch["minItems"]:
            errs.append("%s: 条目数 %d < %d" % (path, len(inst), sch["minItems"]))
        if "maxItems" in sch and len(inst) > sch["maxItems"]:
            errs.append("%s: 条目数 %d > %d" % (path, len(inst), sch["maxItems"]))
        items = sch.get("items")
        if isinstance(items, dict):
            for i, v in enumerate(inst):
                check(v, items, root, "%s[%d]" % (path, i), errs)

    if isinstance(inst, dict):
        for k in sch.get("required") or []:
            if k not in inst:
                errs.append("%s.%s: 缺少必填字段" % (path, k))
        props = sch.get("properties") or {}
        for k, v in inst.items():
            if k in props:
                check(v, props[k], root, "%s.%s" % (path, k), errs)
            else:
                ap = sch.get("additionalProperties")
                if ap is False:
                    errs.append("%s.%s: 不允许的额外字段（additionalProperties=false）"
                                % (path, k))
                elif isinstance(ap, dict):
                    check(v, ap, root, "%s.%s" % (path, k), errs)


# ---------------------------------------------------------------- 语义层

def validate_semantics(analysis, enums, expected_article_id=None):
    """返回 (errors, warnings)。"""
    errs = []
    warns = []

    if not isinstance(analysis, dict):
        return ["根节点不是对象"], []

    blocks = analysis.get("blocks") or []
    ids = [b.get("id") for b in blocks if isinstance(b, dict)]
    id_set = set(x for x in ids if isinstance(x, str))

    # --- id 唯一
    dup = sorted(set(x for x in ids if ids.count(x) > 1))
    if dup:
        errs.append("blocks.id 重复: %s" % dup)

    # --- 父子闭环（P2）
    covered = []
    for sb in (analysis.get("skeleton") or {}).get("blocks") or []:
        sid = sb.get("id")
        subs = sb.get("subblock_ids")
        if subs is None:
            errs.append("skeleton.%s: 缺少 subblock_ids（P2 必填）" % sid)
            continue
        if not isinstance(subs, list):
            errs.append("skeleton.%s.subblock_ids: 必须是数组" % sid)
            continue
        for s in subs:
            if s not in id_set:
                errs.append("skeleton.%s.subblock_ids 指向不存在的块: %s" % (sid, s))
            elif not str(s).startswith(str(sid) + "-"):
                errs.append("skeleton.%s.subblock_ids 含不属本块的 id: %s" % (sid, s))
            covered.append(s)

    dup_cov = sorted(set(x for x in covered if covered.count(x) > 1))
    if dup_cov:
        errs.append("subblock_ids 被多个大块重复声明: %s" % dup_cov)

    missing = sorted(id_set - set(covered))
    if missing:
        errs.append("以下子块未被任何大块覆盖: %s%s"
                    % (missing[:10], "…" if len(missing) > 10 else ""))
    orphan = sorted(set(covered) - id_set)
    if orphan:
        errs.append("subblock_ids 指向未知块: %s%s"
                    % (orphan[:10], "…" if len(orphan) > 10 else ""))

    # --- depends_on
    for b in blocks:
        if not isinstance(b, dict):
            continue
        for d in (b.get("depends_on") or []):
            if d == "边界可疑":
                continue
            if d not in id_set:
                errs.append("%s.depends_on 指向不存在的块: %s" % (b.get("id"), d))

    # --- relations
    for i, r in enumerate(analysis.get("relations") or []):
        if not isinstance(r, dict):
            continue
        for k in ("from", "to"):
            if r.get(k) not in id_set:
                errs.append("relations[%d].%s 指向不存在的块: %s" % (i, k, r.get(k)))

    # --- three_questions
    qs = (analysis.get("recap") or {}).get("three_questions") or []
    if qs and len(qs) != len(blocks):
        errs.append("recap.three_questions 数量 %d != blocks 数量 %d"
                    % (len(qs), len(blocks)))
    for i, q in enumerate(qs):
        if not isinstance(q, dict):
            continue
        if q.get("block_id") not in id_set:
            errs.append("three_questions[%d].block_id 指向不存在的块: %s"
                        % (i, q.get("block_id")))
        for d in (q.get("depends_on") or []):
            if d == "边界可疑":
                continue
            if d not in id_set:
                errs.append("three_questions[%d].depends_on 指向不存在的块: %s" % (i, d))

    # --- article_id 同源（P3）
    aid = (analysis.get("meta") or {}).get("article_id")
    if expected_article_id is not None and aid != expected_article_id:
        errs.append("meta.article_id=%r 与包目录名 %r 不一致（P3）"
                    % (aid, expected_article_id))

    # --- 契约漂移（P6）
    if enums:
        try:
            schema = load_schema()
            sf = (((schema.get("definitions") or {}).get("function") or {}).get("enum"))
            if sf != enums.get("function"):
                errs.append("契约漂移：schema.definitions.function.enum 与 enums.json 不一致")
            sr = ((((schema.get("definitions") or {}).get("relation") or {})
                   .get("properties") or {}).get("type") or {}).get("enum")
            if sr != enums.get("relation_type"):
                errs.append("契约漂移：schema.relation.type.enum 与 enums.json 不一致")
        except SystemExit:
            warns.append("无法读取 schema，跳过契约漂移检查")

    # --- schema_version 与 enums.version 对齐（软检查）
    sv = analysis.get("schema_version")
    ev = (enums or {}).get("version")
    if sv and ev and sv.split(".")[0] != str(ev).split(".")[0]:
        warns.append("schema_version=%r 与 enums.version=%r 主版本不一致" % (sv, ev))

    return errs, warns


def validate_feynman(feynman, analysis=None):
    """
    校验费曼骨架（analysis/feynman.json）。
    结构：{"max_depth": n, "blocks": {subblock_id: [{level,name,question,rubric}, …]}}
    返回 (ok, errors, warnings)。
    """
    errs, warns = [], []

    if not isinstance(feynman, dict):
        return False, ["费曼骨架根节点不是对象"], []

    depth = feynman.get("max_depth")
    if not isinstance(depth, int) or depth < 1 or depth > 5:
        errs.append("feynman.max_depth 必须是 1-5 的整数（实际 %r）" % depth)
        depth = 5

    blocks = feynman.get("blocks")
    if not isinstance(blocks, dict) or not blocks:
        return False, ["feynman.blocks 必须是非空对象"], []

    valid_ids = set()
    if isinstance(analysis, dict):
        for b in (analysis.get("blocks") or []):
            if isinstance(b, dict) and b.get("id"):
                valid_ids.add(b["id"])

    for bid, layers in blocks.items():
        if valid_ids and bid not in valid_ids:
            errs.append("feynman.blocks.%s 指向不存在的子块" % bid)
        if not isinstance(layers, list) or not layers:
            errs.append("feynman.blocks.%s 必须是非空数组" % bid)
            continue
        if len(layers) > depth:
            errs.append("feynman.blocks.%s 层数 %d 超过 max_depth %d"
                        % (bid, len(layers), depth))

        levels = []
        for i, ly in enumerate(layers):
            if not isinstance(ly, dict):
                errs.append("feynman.blocks.%s[%d] 不是对象" % (bid, i))
                continue
            lvl = ly.get("level")
            if not isinstance(lvl, int):
                errs.append("feynman.blocks.%s[%d].level 缺失或非整数" % (bid, i))
            else:
                levels.append(lvl)
            if not (ly.get("question") or "").strip():
                errs.append("feynman.blocks.%s[%d].question 为空" % (bid, i))

            r = ly.get("rubric")
            ok_r = False
            if isinstance(r, str):
                ok_r = bool(r.strip())
            elif isinstance(r, dict):
                ok_r = any(
                    isinstance(v, list) and any(str(x).strip() for x in v)
                    for v in r.values()
                )
            if not ok_r:
                errs.append("feynman.blocks.%s[%d].rubric 为空" % (bid, i))

        if levels and levels != sorted(levels):
            errs.append("feynman.blocks.%s 的 level 未按升序排列：%s" % (bid, levels))
        if levels and levels != list(range(1, len(levels) + 1)):
            warns.append("feynman.blocks.%s 的 level 不连续：%s" % (bid, levels))

    return (len(errs) == 0), errs, warns


# ---------------------------------------------------------------- 入口

def validate_analysis(analysis, enums=None, expected_article_id=None, schema=None):
    """返回 (ok, errors, warnings)。"""
    if schema is None:
        schema = load_schema()
    if enums is None:
        enums = load_enums()
    errs = []
    check(analysis, schema, schema, "$", errs)
    sem, warns = validate_semantics(analysis, enums, expected_article_id)
    errs.extend(sem)
    return (len(errs) == 0), errs, warns


def main(argv=None):
    ap = argparse.ArgumentParser(description="analysis.json 严格校验器（schema + 语义）")
    ap.add_argument("paths", nargs="*", help="analysis.json 路径")
    ap.add_argument("--id", help="期望的 article_id（通常等于 corpus/<id> 目录名）")
    ap.add_argument("--all", action="store_true", help="校验 corpus/*/analysis/analysis.json 全部")
    ap.add_argument("--quiet", action="store_true", help="只输出汇总")
    args = ap.parse_args(argv)

    targets = list(args.paths)
    if args.all:
        corpus = ROOT / "corpus"
        if not corpus.is_dir():
            fail("corpus/ 不存在")
            return 5
        for pkg in sorted(corpus.iterdir()):
            p = pkg / "analysis" / "analysis.json"
            if p.is_file():
                targets.append(str(p))
    if not targets:
        ap.error("需要提供 analysis.json 路径，或使用 --all")

    rc = 0
    for path in targets:
        p = Path(path)
        if not p.is_file():
            fail("文件不存在: %s" % p)
            rc = 5
            continue
        try:
            analysis = read_json(p)
        except Exception as e:
            fail("%s 解析失败: %s" % (p, e))
            rc = 5
            continue

        expected = args.id
        if expected is None:
            # 从 corpus/<id>/analysis/analysis.json 推断包目录名
            pp = p.resolve()
            if pp.parent.name == "analysis" and pp.parent.parent.parent.name == "corpus":
                expected = pp.parent.parent.name

        try:
            ok, errs, warns = validate_analysis(analysis, expected_article_id=expected)
        except SystemExit as e:
            fail(str(e))
            return 5

        tag = "[ok]  " if ok else "[FAIL]"
        try:
            shown = p.resolve().relative_to(ROOT)
        except ValueError:
            shown = p
        log("%s %s" % (tag, shown))
        if not args.quiet:
            for w in warns:
                log("    [warn] " + w)
            for e in errs[:40]:
                log("    " + e)
            if len(errs) > 40:
                log("    … 另有 %d 条错误未显示" % (len(errs) - 40))
        if not ok:
            rc = 1
        elif not args.quiet:
            log("    schema + 语义校验通过（%d 块 / %d 关系 / %d 三问）"
                % (len(analysis.get("blocks") or []),
                   len(analysis.get("relations") or []),
                   len((analysis.get("recap") or {}).get("three_questions") or [])))

    return rc


if __name__ == "__main__":
    sys.exit(main())
