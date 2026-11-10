# pass4 · 逐块分析

## 本轮任务

逐块回答四个结构问题：这一块**为什么存在**（purpose）、**凭什么这么说**（basis）、**依赖哪一块**（depends_on）、**关键点是什么**（key_points）。逐块处理，不跨块合并。

## 输入字段

- `blocks[]`：pass2 的功能块（`id` / `time_range` / `function` / `summary`）。
- `relations[]`：pass3 的关系边（只作参考，可用于判断依赖方向）。
- `segments[]`：原文段落，用 `time_range` 定位每块覆盖的原文，作为 `basis` 的依据。

## 输出字段

```json
{
  "blocks": [
    {
      "id": "b1",
      "purpose": "这一块在整篇文章里承担什么任务（一句话）",
      "basis": "作者凭什么这么说：依据哪些原文内容",
      "depends_on": ["b1", "边界可疑"],
      "key_points": ["关键点 1", "关键点 2"],
      "confidence": "medium"
    }
  ]
}
```

- 每个输入块必须有一条输出，不能漏。
- `key_points` 用短句，一条一个观点，最多 5 条。
- `confidence` 可选（`high` / `medium` / `low`）：填写你对这一块分析的可靠程度；不填时 `run_pipeline.py` 按 `medium` 处理。

## depends_on 与 basis 定义

1. `depends_on` 只填以下两类来源，**按类型区分方向**：
   - `type = 因此` 且 `to = 当前块`：取该边的 `from` 块加入 `depends_on`。依据：from 推出 to，to 依赖 from。
   - `type = 依赖` 且 `from = 当前块`：取该边的 `to` 块加入 `depends_on`。依据：from 依赖 to，from 需要 to 作为前提。
   - `type = 依赖` 且 `to = 当前块`：不取。当前块是前提提供者，不是依赖者。
   - `type = 因此` 且 `from = 当前块`：不取。当前块是前序，不被自己的后继依赖。
   `铺垫`、`例如`、`但是`、`反驳` 的入边和出边都不进 `depends_on`，只作 context。
2. `depends_on` 必须引用 `relations` 里真实存在的子块 id。若当前块没有任何 `依赖/因此` 入边，写空数组 `[]`，不要自创依赖；若 summary 显示明显依赖但 `relations` 缺边，写 `["关系边缺失：<原因>"]`，不要硬填一个 id。
3. `basis` 写块内内容依据（定义、数据、前提、原文论断），不是块间依赖；块间依赖只写进 `depends_on`。

## 禁止事项

- 禁止写 `author_says`（原文引用属于 pass5）、`my_inferences` / `my_examples` / `my_questions`、`recap`。
- 禁止修改块的 `function`、`time_range`、`id`。
- 禁止用空数组敷衍 `key_points`；一块确实没有关键点时写 `[]` 并在 `basis` 里说明原因。
- 禁止输出 JSON 以外的任何文字。
