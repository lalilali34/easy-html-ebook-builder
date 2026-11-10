# pass6 · 复述检验

## 本轮任务

用复述检验结构是否真的建好了：一句话结论、主要步骤、每个功能块的三问（为什么需要这块 / 凭什么 / 依赖什么）。

## 输入字段

- `skeleton`：`core_problem`、`core_conclusion`、`blocks[]`。
- `blocks[]`：pass4 的块分析。
- `relations[]`：pass3 的关系边。

## 输出字段

```json
{
  "one_sentence": "用一句话复述全文：问题 + 结论",
  "main_steps": ["第一步", "第二步", "第三步"],
  "three_questions": [
    {
      "block_id": "b2",
      "why_needed": "这一块为什么必须存在",
      "basis": "凭什么这样说：引用块里的依据或原文",
      "depends_on": ["b1"]
    }
  ]
}
```

- `main_steps` 按讲解顺序排列，覆盖主要功能块。
- `three_questions` 覆盖全部子块：每个子块一条，`block_id` 必须是子块 id（bN-M），不得用大块 id。
- `depends_on` 只能填已存在 id 或 `边界可疑`。

## main_steps 压缩规则

- 按 pass1 的 7 个大块（b1–b7）压缩成 5–7 步，每步对应一个大块或两个相邻大块的合并。
- 不要按 29 个子块展开成 29 步。
- 每步写「大块功能 + 一句话内容」，不写子块 id（bN-M）。

## three_questions 字段映射

- `why_needed`：不能直接抄 pass4 的 purpose。要回答「如果删掉这一块，全文论证会缺什么」，必须包含「缺了它，……就无法成立/无法过渡」这类结构判断。
- `basis`：可以引用 pass4 的 basis，但必须压缩成一句，不能整段复制；如果 basis 里有多个依据，只保留最关键的一个。
- `depends_on`：直接取 pass4 的 depends_on 数组，不要改写、不要新增、不要删除；如果 pass4 的 depends_on 是 []，three_questions 里也写 []，不要为了「看起来完整」硬填。
- `three_questions` 覆盖 29 个子块每个一条，不能只写 7 个大块；id 用子块 id（bN-M），不用大块 id。

## 三问问不上来怎么办

- 如果某个块的 `why_needed` 或 `basis` 答不上来，不要硬编。在该条的 `why_needed` 前加标记 `结构未建好：`，写明缺什么，并把 `depends_on` 写为 `["边界可疑"]`。
- 如果超过一块答不上来，`one_sentence` 也不得给出确定结论，改为 `结构未建好：<缺什么>`。
- 这种情况必须作为本轮失败信号上报（validate 会把 `结构未建好：` 视为结构缺陷提示，但不会自动删数据）。

## 禁止事项

- 禁止重新生成 author_says、relations、purpose、basis 的新版本；只能引用已有字段。
- 禁止读原始字幕或 cleaned.jsonl；pass6 只吃前序轮产物。
- 禁止把 one_sentence 写成两句话或一段话；一句话就是一句话。
- 禁止新增分析内容（`basis` 只能引用前面 pass 已确证的内容）。
- 禁止把三问写成"作者为什么这样说"的主观猜测。
- 禁止输出 JSON 以外的任何文字。
