# pass2 · 功能块

## 本轮任务

先把每个段落打上功能标签，再把**相邻且同功能**的段落合并成功能块。只做"哪几句话说的是同一件事"，**不解释内容细节**。

## 输入字段

- `segments[]`：预处理后的字幕（`start` / `end` / `text`）。
- `skeleton`：pass1 输出的 `core_problem`、`core_conclusion`、`blocks[]`（仅作参照，可微调边界）。

## 输出字段

```json
{
  "segment_labels": [
    { "start": 0.0, "end": 2.4, "function": "提出问题" },
    { "start": 2.6, "end": 5.1, "function": "提出问题" }
  ],
  "blocks": [
    {
      "id": "b1",
      "time_range": { "start": 0.0, "end": 8.2 },
      "function": "提出问题",
      "summary": "不超过 40 字，只写这一块在做什么"
    }
  ]
}
```

- `segment_labels` 必须覆盖输入 `segments` 的全部时间区间，不得漏段。
- 合并后块内段落必须**相邻**且 `function` 相同。
- `blocks` 的 id 从 `b1` 连续编号，`time_range` 等于其内首段 `start` 与末段 `end`。

## 禁止事项

- 禁止写 `purpose`、`basis`、`key_points`、`author_says`、`my_*`、`confidence`、`relations`、`recap`。
- 禁止把不同功能的段落强行合并成一个块。
- 禁止用 `过渡` 标签掩盖没想清楚的段落；确实只是衔接才标 `过渡`。
- 禁止输出 JSON 以外的任何文字。
