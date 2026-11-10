# pass1 · 骨架

## 本轮任务

只看整体，输出文章骨架：核心问题是什么、核心结论是什么、讲者把它拆成了哪几个大块。**不展开任何细节。**

## 输入字段

- `meta.title` / `meta.source` / `meta.duration` / `meta.chapters`：视频标题、来源、总时长（秒）、已有分段（可为空）。
- `segments[]`：预处理后的字幕，每条含 `start`（秒）、`end`（秒）、`text`（合并后的句子）。

## 输出字段

```json
{
  "core_problem": "用一句话写清讲者要回答的问题",
  "core_conclusion": "用一句话写清讲者的核心结论",
  "blocks": [
    {
      "id": "b1",
      "time_range": { "start": 0.0, "end": 8.2 },
      "function": "提出问题",
      "summary": "不超过 40 字的块摘要"
    }
  ]
}
```

- `blocks` 至少 2 块、通常 3–8 块。
- `function` 只能从封闭集合选：`定义 | 提出问题 | 主张 | 理由 | 证明步骤 | 例子 | 反驳 | 推论 | 过渡 | 结论`。
- `id` 从 `b1` 连续编号；`time_range` 必须落在输入 `segments` 的时间范围内。
- `time_range` 的 `start` / `end` 必须直接取自输入 `segments` 中某几条的 `start` / `end` 边界，不允许自创数值；每一块的 `start` / `end` 都必须能在 `segments` 里找到对应条目。

## 禁止事项

- 禁止写 `purpose`、`basis`、`author_says`、`my_*`、`confidence`、`relations`、`recap`——这些属于后面的 pass。
- 禁止摘录原文句子作为 summary。
- 禁止把同一功能的多个块拆得过细（这里只分大块）。
- 禁止出现覆盖整个输入（如 1.0–808.0）的单一块；若输入只有 1 条 segment，视为粒度不足，最多产出 1 块并在 summary 中注明。
- 序数词（第一是 / 第二是 / 第三是）如果连续出现在相邻几条 segment 内，视为一个功能块内部的列举，不要拆成多个大块；大块划分要看全文的论证阶段，不是看序数词。
- 禁止输出 JSON 以外的任何文字。
