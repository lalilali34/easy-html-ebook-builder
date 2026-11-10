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
      "my_inferences": [
        { "kind": "core",     "claim": "作者这一步的真实意图是什么" },
        { "kind": "forward",  "claim": "如果这个推论成立，还能推出什么（要写清从 A 到 B 的链条）" },
        { "kind": "forward",  "claim": "第二条正向外延" },
        { "kind": "backward", "claim": "如果反过来，哪一部分会塌（要写清矛盾点）" },
        { "kind": "backward", "claim": "第二条反向外延" },
        { "kind": "boundary", "claim": "这个推论在什么条件下失效（可选）" },
        { "kind": "rival",    "claim": "还有别的读法吗，区别在哪（可选）" },
        { "kind": "test",     "claim": "怎么验证它站得住（可选）" }
      ],
      "my_examples": ["我自己补充的例子"],
      "my_questions": ["我仍然存疑的地方"]
    }
  }
}
```

### 硬性数量要求

| kind | 数量 | 必填 |
|---|---|---|
| `core` | **恰好 1** | ✅ |
| `forward` | **恰好 2** | ✅ |
| `backward` | **恰好 2** | ✅ |
| `boundary` | 0 或 1 | ❌ 可选 |
| `rival` | 0 或 1 | ❌ 可选 |
| `test` | 0 或 1 | ❌ 可选 |

**可选三项（boundary / rival / test）宁缺勿滥**：只在确实有内容可写时输出。
写不出就不写这个对象，**不要为了凑数编一句通用的话**。

### 各 kind 的写法要求

**`core`**：作者没说但意图明显的判断。句式是「作者这样写，是为了……」「这意味着……」。

**`forward`**：从核心推论往下推一步，要带链条——
「若 A 成立，那么本文第 X 处也应该如此（而它确实如此）」，或「若 A 成立，读者容易把 B 与 C 混为一谈」。
禁止写成同义反复（「这说明作者很重视这个概念」这种没有推力的句子）。

**`backward`**：假设核心推论不成立，指出**哪一部分会自相矛盾**，并说明作者实际上是怎么做的。
句式是「若不……，则……就讲不通，但作者明说/明明……」。要指向具体内容，不能空泛。

**`boundary`**：这个推论依赖什么前提，前提不成立时会怎样。要具体到某个条件。

**`rival`**：给出另一种同样说得通的读法，并指出**两种读法的分歧点在哪**（不是「也有人认为……」）。

**`test`**：给出一个可在本文内部核对的检验点——「看作者在 X 处是否 Y」。

- 三个基础字段 `my_inferences` / `my_examples` / `my_questions` 都要存在；确实没有时写 `[]`，不能省略。
- `my_examples` / `my_questions` 每条以「我」起句，便于区分。
- `my_inferences` 每条 `claim` 控制在 40–120 字，一句话讲清一个判断。

## 禁止事项

- `author_says` 的 `quote` 必须逐字取自 `cleaned.jsonl`，不得使用 pass1 或任何前序轮的 ASR 还原词。
- my_inferences 不得复述 author_says 的 text 转述句；推断必须包含原文没有直接说出的判断（如“作者这样写是为了……”“这意味着……”），不能只是把转述句换个说法。
- 禁止把推断写进 `author_says`，禁止把作者原话写进 `my_inferences`。
- 禁止在没有 `quote` 或 `timestamp` 的情况下凭空写 `author_says`。
- 禁止在阶段 A 里顺手输出 `my_*`（阶段边界，确认后才做 B）。
- 禁止跨块复制同一句引用（同一作者原话只出现在它实际所在的块）。
- 禁止输出 JSON 以外的任何文字。
