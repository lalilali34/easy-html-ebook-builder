# pass5 · 作者说 / 我的层次（两阶段）

## 本轮任务

分成两个阶段，**确认前一阶段合规后才做后一阶段**：

- 阶段 A：只输出 `author_says`——作者在这块里到底说了什么，逐条带原文引用或时间戳。
- 阶段 B：才输出 `my_inferences` / `my_examples` / `my_questions`——我的推断、我的例子、我的疑问。

## 输入字段

- `blocks[]`：pass4 的块（含 `purpose` / `basis` / `depends_on` / `key_points`）。
- `segments[]`：原文段落，用于逐字摘 `quote` 和定位 `timestamp`。

## 阶段 A 输出字段

```json
{
  "author_says": {
    "b1": [
      { "text": "对作者这句的转述", "quote": "原文逐字引用", "timestamp": 2.6 }
    ]
  }
}
```

- 每条至少带 `quote` 或 `timestamp` 之一；能从原文逐字摘就同时给。
- `quote` 必须与输入 `segments[].text` 逐字一致。
- `text` 是转述，可以概括，但不得在转述里掺入作者没说的判断。

## 阶段 B 输出字段

```json
{
  "my_layer": {
    "b1": {
      "my_inferences": ["我从结构读出来、但作者没明说的判断"],
      "my_examples": ["我自己补充的例子"],
      "my_questions": ["我仍然存疑的地方"]
    }
  }
}
```

- 三个字段都要存在；确实没有时写 `[]`，不能省略。
- 每条以"我推断/我觉得/我会/我想问"等第一人称起句，便于区分。

## 禁止事项

- `author_says` 的 `quote` 必须逐字取自 `cleaned.jsonl`，不得使用 pass1 或任何前序轮的 ASR 还原词。
- my_inferences 不得复述 author_says 的 text 转述句；推断必须包含原文没有直接说出的判断（如“作者这样写是为了……”“这意味着……”），不能只是把转述句换个说法。
- 禁止把推断写进 `author_says`，禁止把作者原话写进 `my_inferences`。
- 禁止在没有 `quote` 或 `timestamp` 的情况下凭空写 `author_says`。
- 禁止在阶段 A 里顺手输出 `my_*`（阶段边界，确认后才做 B）。
- 禁止跨块复制同一句引用（同一作者原话只出现在它实际所在的块）。
- 禁止输出 JSON 以外的任何文字。
