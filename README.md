# ebook-pipeline

把一份**纯文本讲义 / 字幕稿**，自动变成一本带结构化图谱、术语悬浮解释、补充例子的**单文件 HTML 电子书**，并自动上架到书架。

> **维护约定**：项目的目录结构、命令、数据契约、渲染行为发生**大改动**时，必须同步更新本文件（见文末「维护约定」）。小改（改文案、调颜色）不必。

> **字体说明**：仓库**不含字体文件**。`downstream/themes.md` 中声明了三款中文字体，运行时需自行放入
> `downstream/assets/fonts/`（`hanyi.woff2` / `wangtianxi.woff2` / `loli.woff2`）。缺失时会回退到系统字体，
> 页面仍可正常显示，只是字形不同。字体版权归各自厂商所有，请自行取得授权。

> **示例数据**：`corpus/20261110_knowledge-why-forget/` 是**完全原创的演示样本**（《为什么我们记不住读过的书》），
> 不含任何第三方内容，可自由使用、修改、再分发。

---

## 1. 它做什么

```
  txt / md
     │
     ▼
  ① 入库 ──→ corpus/<id>/{source,analysis,text}/
     │
     ▼
  ② 分析 ──→ analysis.json + article.md + terms/<id>.md
     │        （pass1–pass8，超长自动分块压缩）
     ▼
  ③ 发布 ──→ deliver.json（带 sha256 的交付清单，原子写）
     │
     ▼
  ④ 渲染 ──→ build/<id>.html（正文 / 图谱 / 术语 三 Tab 合一）
     │
     ▼
  ⑤ 上架 ──→ site/index.html 书架
```

一条命令跑完 ①–⑤：

```powershell
python upstream\src\full_auto.py --file "inbox\某篇.md"
```

或者把文件**直接拖到项目根的 `ebook-pipeline.exe` 上**。

---

## 2. 快速开始

### 2.1 配置 API Key（一次性）

```powershell
cd D:\DSH_workplace\ebook-pipeline
Copy-Item .env.example .env
notepad .env
```

填入：

```ini
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=sk-你的key
LLM_MODEL=deepseek-chat
```

`.env` 已被 `.gitignore` 忽略，**不会进版本库**。

自检：

```powershell
python upstream\src\llm_client.py --ping
# 期望：[ok] OK
```

### 2.2 跑第一篇

```powershell
# 方式 A：命令
python upstream\src\full_auto.py --file "inbox\某篇.md" --slug my-article

# 方式 B：拖拽
# 把 .md / .txt 拖到 ebook-pipeline.exe 上
```

产出：

```
corpus\<日期>_<slug>\build\<日期>_<slug>.html   ← 打开看
site\index.html                                  ← 书架
```

### 2.3 无 Key 时先验管线

```powershell
python upstream\src\full_auto.py --file "inbox\某篇.md" --dry-run
```

只生成 `*.dryrun.*` 占位产物，**不覆盖正式文件、不发布、不上架**。

---

## 3. 目录结构

```
ebook-pipeline/
├── ebook-pipeline.exe          # 拖拽启动器（生成物，不入库）
├── .env / .env.example         # LLM 配置（.env 不入库）
├── .gitignore
│
├── contract/                   # 【契约层】上下游共读，单一真源
│   ├── analysis.schema.json    # analysis.json 的 JSON Schema（P1–P6 补丁版）
│   └── enums.json              # 功能标签/关系类型/术语类型等封闭集合
│
├── upstream/                   # 【上游】文本 → 结构化
│   ├── src/
│   │   ├── inbox_ingest.py     # ① 入库：标题→slug→日期→建骨架 + raw.md
│   │   ├── pipeline.py         # ② 分析：pass1–8 编排 + 超长分块压缩
│   │   ├── llm_client.py       # OpenAI 兼容客户端（零依赖，urllib）
│   │   ├── publish.py          # ③ 发布：生成 deliver.json
│   │   ├── validate.py         # 严格校验：schema 层 + 语义层
│   │   └── full_auto.py        # 一条命令串起 ①②③⑤
│   └── prompts/                # 11 个提示词（agent + pass1–8）
│
├── downstream/                 # 【下游】结构化 → HTML
│   ├── src/
│   │   ├── render.py           # ④ 渲染：三 Tab 合一 + 幂等指纹
│   │   └── build_index.py      # ⑤ 书架聚合
│   ├── templates/tab-shell.html# 三 Tab 外壳模板
│   ├── themes.md               # 样式唯一来源（CSS 全在这里）
│   └── assets/
│       ├── fonts/              # 三款中文字体（本地，离线可用）
│       └── heti/               # heti 排版资源（本地，去 CDN）
│
├── corpus/                     # 【文章包】唯一交汇处
│   └── <YYYYMMDD>_<slug>/
│       ├── source/
│       │   ├── raw.md          # 入库后的正文（首行 # 标题）
│       │   ├── orig.*          # 原始文件副本（不入库）
│       │   └── frontmatter.txt # 若原文有 YAML frontmatter，剥离到这里
│       ├── analysis/
│       │   ├── analysis.json   # 核心产物
│       │   ├── feynman.json    # 费曼练习骨架（pass9，可选）
│       │   └── pass.*.json     # 各轮原始响应（本地缓存，不入库）
│       ├── text/
│       │   ├── article.md
│       │   └── article_with_examples.md
│       ├── deliver.json        # 交付清单（生成物，不入库）
│       └── build/              # 渲染产物（不入库）
│
├── terms/                      # 【术语】按篇隔离
│   ├── <id>.md                 # 本篇系统术语表
│   └── _index.json
│
├── personal_terms/             # 【个人术语】按篇隔离，自由格式笔记（入库）
│   └── <id>.md
│
├── site/index.html             # 书架（生成物，不入库）
│
└── tools/                      # 运维工具
    ├── launcher.py             # 拖拽启动器源码（打包成 exe）
    ├── backfill_analysis.py    # 给已有 analysis.json 补契约字段
    ├── rerun_examples.py       # 只重跑 pass7s（补充例子）
    ├── make_test_sample.py     # 合成回归样本
    └── migrate_stage1.py       # 一次性旧结构迁移
```

---

## 4. 流水线细节

### 4.1 入库（inbox_ingest.py）

- 标题优先级：`# 标题` → 首个 ≤60 字的非分隔线行 → **文件名兜底**
- 剥离 YAML frontmatter（未闭合的 `---` 当误写分隔线丢弃）
- slug 优先级：英文词 → pypinyin（若已安装）→ `article-<sha1前6位>`
- 处理完的源文件归档到 `_archive/consumed/<时间戳>/`（不删除）
- 支持 `.txt` / `.md`；`.srt` / `.vtt` **暂不支持**

### 4.2 分析（pipeline.py）

- pass0 **ASR 纠错**（可选）→ pass1 骨架 → 逐大块 pass2 出子块 → pass3 关系 → pass4 逐块 → pass5 两阶段（author_says / **六层推论 + 自评**）→ pass6 复述 → pass7 成文 → pass7s 例子 → pass8 术语 → pass9 费曼练习骨架（可选）
- **pass0 拆字幕**：入库时检测时间码（>30% 行以 `mm:ss` 开头）→ 剥离 + 按 150 字并段；写 `source/ingest.json` 的 `is_subtitle`，pipeline 据此自动决定跑不跑 ASR 纠错（拖拽入口零配置）
- **pass0 纠错**：只自动应用 `confidence=high` 的修正，全部对照落 `analysis/asr_fixes.json`；修好的正文写 `source/raw.fixed.md`，原始 `raw.md` 永不覆盖
- **pass5 分批**：每批 3 块调用（一次塞全部 blocks 时模型会返回扁平数组而丢掉 block_id 归属）
- **超长分块**：超过 `--max-chars`（默认 **24000**）时，按段落均衡切块 → 每块压缩到 30–40% → 用压缩稿继续跑
- **伪时间轴**：纯文本没有秒数，按段落序号生成等距时间轴（每段 10 秒）
- 每轮原始响应落盘到 `analysis/pass.<tag>.json`，`--resume` 可复用（失败重跑不重烧 token）；pass9 的缓存会自校验"返回子块数"，不足时自动重跑该批
- 模型返回结构会漂移（dict/list 互换），代码里有归一化层兜底

### 4.3 发布（publish.py）

`deliver.json` 是唯一握手文件，**原子写**（先写 `.tmp` 再 `os.replace`）。下游只认 `status == "ready"` 且 sha256 校验通过的包。

```json
{
  "schema_version": "1.0",
  "article_id": "20261109_xuanjian-xianzu",
  "status": "ready",
  "artifacts": [{ "kind": "analysis", "path": "...", "sha256": "..." }],
  "stats": { "skeleton_blocks": 8, "subblocks": 18, "relations": 19 },
  "checks": { "analysis_schema": "pass", "terms_file": "pass" }
}
```

`checks` 任一非 `pass` → 下游**拒绝渲染**（拒绝比渲出错页好）。

### 4.4 渲染（render.py）

- 三 Tab：**正文 / 图谱 / 术语**，单文件，零前端框架；有费曼骨架时**追加第四 Tab「练习」**（无骨架自动隐藏，老文章兼容）
- **练习 Tab**：每层一个作答框 + 三态标记（未开始/进行中/完成），顶部可选目标深度；
  作答存 localStorage（`feynman_notes:<id>`），「保存练习」统一落盘，「导出 JSON」下载整篇文件；
  关闭页面前有未保存修改会被 `beforeunload` 拦截；导出文件用 `tools/import_feynman.py` 拆成
  `feynman/<id>/<subblock_id>.json`（严格对齐规格字段）
- **四维自评清单**：`feynman.json` 的 `rubric` 是四维对象（`concept` 核心概念 / `logic` 逻辑链条 /
  `boundary` 边界条件 / `application` 场景应用），按层选维（L1 概念、L2 概念+逻辑、L3 边界+应用、L4 逻辑、L5 边界）；
  渲染成四色标签的折叠清单（蓝/黄/红/绿），旧格式字符串自动降级为单组清单
- 正文：句级分段（每句一个 `<p class="sent">`），段末句带 `sent-last`，用 CSS 区分句间距与段间距
- 图谱：`skeleton.blocks[].subblock_ids` 显式父子结构 → 折叠卡片
- **推论六层（v0.6）**：`my_inferences` 是 `{kind, claim}` 数组——`core` 1 条 + `forward` 2 条 + `backward` 2 条为必填，
  `boundary` / `rival` / `test` 可选（AI 判断有没有真东西，没有就不写）；渲染按层分组带小标题
- **原文质量评估**：块底部的 `evaluation` 评的是**作者**（七维度：文本忠实度 / 概念辨析 / 历史语境 /
  辩证深度 / 可证伪性 / 立场预设 / 解释力），AI **自选适用维度**（通常 2–4 个），老数据回退显示 `confidence`
- **AI 自我反思**：`self_reflection` 与「我的疑问」同级，只评 AI 自己的处理（引文完整性 / 是否越界补充）
- 术语：本篇 `<id>.md` 内最长匹配，渐变下划线，**JS 浮层**（不是 CSS 伪元素）
- **双浮层（v0.6）**：系统层（冷色蓝边）+ 个人层（暖色橙边）。个人笔记来自 `personal_terms/<id>.md`；
  两层区间完全重合时合并为一个 span 双属性（`data-tooltip` + `data-personal`），
  部分重叠时**系统优先、个人让位**并告警；`hide: true` 抑制该位置的系统层
- 术语 Tab 末尾附「📝 我的笔记」区块，列出全部个人条目
- **笔记编辑（浏览器内）**：浮层右上角 `✏️` → 编辑 → 确定（先进内存暂存）→ 右下角「保存笔记」统一写入 localStorage；
  存在未保存修改时关闭页面会被 `beforeunload` 拦截提醒；「导出 md」下载后手动放回 `personal_terms/` 即固化
- 排版：侧边目录（右侧，sticky）、渐变进度条、小标题 42px + 序号、书名 55px
- **完全离线**：字体与 heti 都是本地资源（`downstream/assets/fonts/`、`downstream/assets/heti/`），零外网依赖；
  路径由 `render.py` 按输出目录动态计算相对路径
- **幂等**：inputs 指纹包含 deliver / renderer 自身 / analysis / article / terms / **personal_terms** / **feynman** / themes / template

### 4.5 书架（build_index.py）

扫 `corpus/*/deliver.json`，生成 `site/index.html`。

---

## 5. 数据契约

### 5.1 analysis.json（contract/analysis.schema.json）

顶层必须包含：`schema_version` / `meta` / `skeleton` / `relations` / `blocks` / `recap`。

关键约束（P1–P6 补丁）：

| 补丁 | 内容 |
|---|---|
| P1 | `depends_on` 允许指向子块（`b1-2`），不再只限大块 |
| P2 | `skeleton.blocks[].subblock_ids` **必填**，显式声明父子 |
| P3 | `meta.article_id` **必填**，与目录名、deliver 三处同源 |
| P4 | `recap.three_questions` 不设上限，语义要求数量 == 子块数 |
| P5 | 顶层 `schema_version: "1.0"` |
| P6 | `enums.json` 与 schema 内联枚举必须一致（防漂移） |

**block 层的我的层次字段（v0.6 扩展）**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `my_inferences` | `[{kind, claim}]` 或 `[string]` | 六层推论。`kind` ∈ core / forward / backward / boundary / rival / test；旧数据为字符串数组，`anyOf` 兼容 |
| `my_examples` | `[string]` | 每条挂靠一条 `forward`，写法「（对应正向外延①）……」 |
| `my_questions` | `[string]` | 每条挂靠一条 `backward`/`boundary` |
| `self_reflection` | `string`（可选） | AI 对自己这块分析的反思，只评自己、不重复 `evaluation` |
| `evaluation` | `[{dim, score, note}]`（可选） | **评原文/作者**的七维度自评，AI 自选适用维度（通常 2–4 个） |
| `confidence` | `string` | 旧字段，无 `evaluation` 时渲染回退用它 |

严格校验：

```powershell
python upstream\src\validate.py --all
```

### 5.2 terms/&lt;id&gt;.md

8 列表格，编号列**留空**（渲染时动态编号）：

```
| 编号 | 词条名 | 别名/匹配形式 | 类型(1-5) | 解释文字 | 链接 | 匹配范围 | 排除/备注 |
```

类型：1 地点 / 2 概念 / 3 人物 / 4 著作 / 5 事件。

解释文字**不限字数**，但必须结合本文语境（严禁字典式解释），并**交代学派 / 流派 / 理论家归属**
（写「布迪厄的惯习概念」而不是「一种行为倾向」）。

同一词条在本篇有多种用法时**拆成多行**，渲染端按正文出现次序依次取用
（第 1 行配第 1 次出现，第 2 行配第 2 次）。

### 5.3 文章 id 规范

```
<YYYYMMDD>_<slug>
slug: [a-z0-9][a-z0-9_-]*
```

目录名、`deliver.json.article_id`、`analysis.json.meta.article_id` 三处必须一致。

### 5.4 personal_terms/&lt;id&gt;.md（个人术语）

按篇隔离、自由格式，只有最小解析锚点：

```markdown
## 惯习
match: habitus, 习性
scope: 布迪厄 / 教育社会学
hide: false

（以下自由文本，支持换行与列表）
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `## 词条名` | ✅ | 条目边界 |
| `match:` | — | 匹配形式，逗号/顿号分隔；缺省用词条名 |
| `scope:` | — | 学派/理论家标注，仅展示，不参与匹配 |
| `hide:` | — | `true` 时抑制该位置对应的**系统层**浮层 |

解析失败（无 `##`、条目无名、编码错误）→ **降级为仅系统层 + 告警**，不拒绝渲染。

### 5.5 feynman/&lt;id&gt;/&lt;subblock_id&gt;.json（练习记录）

浏览器「练习」Tab 导出整篇 JSON，再用 `tools/import_feynman.py` 拆成本文件。

| 字段 | 来源 | 说明 |
|---|---|---|
| `article_id` / `subblock_id` | 渲染上下文 | |
| `max_depth` | **骨架 `analysis/feynman.json`** | 由 `--feynman-depth` 决定，**不是**用户设置值 |
| `target_depth` | 页面内选择 | 钳制到 ≤ `max_depth` |
| `layers[].level/name/question/rubric` | **骨架** | 只读，导出时从 DOM 取，不重新生成 |
| `layers[].answer` | 浏览器作答 | |
| `layers[].status` | 三态标记 | `not_started` / `in_progress` / `done` |
| `layers[].gaps` | 从 `answer` 解析 | 见下 |
| `layers[].feedback` | **恒为 `""`** | 见下 |
| `exported_at` | 导出时刻 | |

**两处与规格 2.5 的刻意偏离（MVP 取舍，不是 bug）：**

1. **`feedback` 永远为空字符串。** 规格让它装"运行反馈"，但 MVP 没有独立反馈输入框——
   用户自评通过对照 rubric 完成。字段保留占位，将来接自动评分时直接填，结构不改。
2. **`gaps` 从 `answer` 正文解析，不是 `feedback`。** 在作答里写 `[[b2-3]]` 或 `[[某个概念]]`，
   导出时解析成 `{ "kind": "manual", "ref": "b2-3", "note": "标记所在句前后 40 字" }`。
   **`answer` 原样保留 `[[...]]` 标记字符**，不做剥离。
修改本文件会触发重渲（已进幂等指纹）。

---

## 6. 常用命令

```powershell
# 全自动（推荐）
python upstream\src\full_auto.py --file "inbox\某篇.md" --slug my-article

# 分步
python upstream\src\inbox_ingest.py --file "inbox\某篇.md" --slug my-article
python upstream\src\pipeline.py    --id 20261109_my-article
python upstream\src\publish.py     --id 20261109_my-article --auto-render

# 校验
python upstream\src\validate.py --all
python upstream\src\publish.py  --id <id> --verify

# 只重渲染（改样式后）
python downstream\src\render.py --all
python downstream\src\build_index.py

# 只重跑例子（改 pass7s 后）
python tools\rerun_examples.py <id>
python upstream\src\publish.py --id <id> --auto-render

# 只重跑费曼骨架（改 pass9 后迭代）
python tools\rerun_feynman.py <id> --depth 3
python tools\rerun_feynman.py <id> --resume      # 复用已缓存批次

# 把浏览器导出的费曼 JSON 拆成单块记录
# 在项目根运行；默认输出到 feynman/<article_id>/，不依赖当前目录
python tools\import_feynman.py "feynman_<id>.json"

# 断点续跑（某轮失败后）
python upstream\src\pipeline.py --id <id> --resume

# 老文章 ASR 错字修补（raw.md 已丢失时，直接改 analysis.json 的引文）
python tools\fix_analysis_quotes.py <id> --dry-run   # 只看能发现什么
python tools\fix_analysis_quotes.py <id> --apply     # 写回 + 重新发布渲染

# ASR 纠错开关（默认按入库标记自动判断）
python upstream\src\full_auto.py --file x.md --asr-fix      # 强制跑
python upstream\src\full_auto.py --file x.md --no-asr-fix   # 强制跳过
```

---

## 7. 设计决策

| 决策 | 原因 |
|---|---|
| 上下游不合并代码，只耦合 `deliver.json` | 任一侧可单独重构、单独重跑 |
| `deliver.json` 原子写 + sha256 | 下游永不读到半截产物；可检测串包 |
| 下游进程内 import 调用（不用 subprocess） | 打包成 exe 后 `sys.executable` 指向启动器自身 |
| exe 只做启动器，代码动态加载 | 改 `.py` 不用重新打包 |
| 术语按篇隔离，无全局池 | 跨文章误标（文学术语匹配法权文章） |
| 句级分段 + 三段间距 | 短句成段的节奏感依赖"句间/段间/节间"分层 |
| 主题 CSS 只在 `themes.md` | 单一真源，render.py 只提取 ```css 代码块 |

---

## 8. 已知限制

1. **纯文本伪时间轴**：txt 没有秒数，图谱 Tab 显示的是"段落序号 × 10 秒"，不是真实时间。
2. **压缩有损**：超 24000 字时分块压缩，子块数会明显减少（实测 10 vs 18）。阈值可调，但不压缩受模型上下文限制。
3. **不支持字幕格式**：`.srt` / `.vtt` 需先转 txt。
4. **首次真跑会消耗较多 token**：一篇约 15–20 次 API 调用。
5. **图谱 Tab 不做术语高亮**：只有正文和术语 Tab 有。
6. **exe 不入库**：`*.exe` 已忽略，换机器需用 `tools/launcher.py` 重新打包（见下）。

### 重新打包 exe

仅当改动 `tools/launcher.py` 本身或升级 Python 时需要：

```powershell
python -m PyInstaller --onefile --console --name ebook-pipeline `
  --distpath dist --workpath build_pyi --specpath build_pyi --noconfirm tools\launcher.py
Copy-Item dist\ebook-pipeline.exe . -Force
```

> `launcher.py` 顶部有一份**静态 import 清单**（argparse/json/html/urllib…），那是给 PyInstaller 收集标准库用的。项目代码新增标准库依赖时，要把对应模块补进那个清单，否则打出的 exe 会 `ModuleNotFoundError`。

---

## 9. 维护约定

- **大改动必须更新本文件**：目录结构、命令、数据契约、渲染模式、打包方式任一变化，都要同步改 README 对应章节，并在下方「里程碑」追加一条。
- **新增上游模块**：必须同步检查 `tools/launcher.py` 的静态 import 清单。
- **改 `contract/`**：必须同时跑 `validate.py --all` 确认现有文章仍通过。
- **改 `themes.md` / 模板**：`render.py --all` 会自动全量重渲（指纹覆盖），不需要 `--force`。
- **新增文章包**：`corpus/<id>/` 的 `analysis.json`、`text/*.md`、`source/raw.md` 入库；`build/`、`pass.*.json`、`orig.*`、`deliver.json` 不入库。
- **个人术语**：`personal_terms/<id>.md` **入库**（个人知识资产），且必须进渲染指纹（已实现）。

---

## 10. 里程碑

| 日期 | 内容 |
|---|---|
| 2026-11-09 | v0.1 上下游合并为 ebook-pipeline，三 Tab 合一渲染跑通首篇 |
| 2026-11-09 | v0.2 双书并存；落地 Schema P1–P6；严格校验器 `validate.py` |
| 2026-11-09 | v0.3 inbox 入库、分块编排 `pipeline.py`、`llm_client.py`、`full_auto.py`；真实文本首次全流程跑通 |
| 2026-11-09 | v0.4 拖拽 exe；下游改进程内调用以兼容打包 |
| 2026-11-09 | v0.5 排版升级：句级分段、右侧目录、渐变进度条、小标题 42px、JS 术语浮层 |
| 2026-11-09 | v0.6 线1：双术语浮层（系统层 + `personal_terms/` 个人层）、hide 抑制、术语 Tab 笔记区；pass8 增加学派归属与拆行规则 |
| 2026-11-09 | v0.6 线2 阶段A：pass9 费曼骨架（5 层 rubric）、`--feynman-depth`、第四 Tab 只读展示、`rerun_feynman.py` 迭代工具 |
| 2026-11-09 | v0.6 线2 阶段B：练习作答框 + 三态标记 + localStorage + 未保存拦截 + 导出 JSON，`import_feynman.py` 拆分入库 |
| 2026-11-10 | v0.6 线2C：缺口回链（`[[b2-3]]` 跳块、`[[术语]]` 唤起浮层）、自评清单折叠、导出文件名带时间戳 |
| 2026-11-10 | v0.6 收尾：主题拆三层色板（底/术语/例子）、术语 WangTianxi 1.3em、pass0 ASR 纠错、字幕时间码剥离 |
| 2026-11-10 | v0.6 增强：pass5 推论六层（核心+正反外延必填）、原文质量评估（七维度 AI 自选）、AI 自我反思 |
| 2026-11-10 | v0.6 增强：heti 本地化（去 CDN）、`fix_analysis_quotes.py` 修补老文章错字、图谱字号放大、背景三层叠加 |
| 2026-11-10 | v0.6 增强：pass9 rubric 改四维诊断（概念/逻辑/边界/应用），按层选维 + 四色标签渲染 |

---

## 11. 开源说明

- **许可**：[MIT](LICENSE)。可自由使用、修改、商用，保留版权声明即可。
- **字体**：仓库不含字体文件。`themes.md` 里声明的三款字体需自行购买/取得授权后放入
  `downstream/assets/fonts/`。缺失时回退系统字体，功能不受影响。
- **示例数据**：仅 `corpus/20261110_knowledge-why-forget/`（原创演示样本，可自由使用）。真实文章数据不在仓库内。
- **隐私**：`.env`（API Key）、`inbox/`（原始素材）、`personal_terms/`（个人笔记）均不入库。
- **贡献**：欢迎 issue / PR，改动请保持"一篇文章一个包、不共享全局状态"的架构约束。
