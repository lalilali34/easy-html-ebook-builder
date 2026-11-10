# 主题套装（themes.md）

> **本文件是渲染器的样式唯一来源。** `downstream/src/render.py` 只提取本文件中的
> ```` ```css ```` 代码块，按顺序拼接后内联进 HTML 的 `<style>`，不读取任何外部 CSS。
>
> 字体路径统一写作 `assets/fonts/`（相对于 `downstream/`）。渲染时会按输出 HTML
> 的实际位置换算成相对路径，因此源文件里不要把路径写死成 `../fonts/` 或绝对路径。
>
> 新增套装 = 新增一个 `## N. 套装名` 小节 + 一个 `body[data-theme="N"]` 代码块，
> 不需要改 render.py。

## 1. 全局基础与字体声明

```css
/* 补充例子基础样式（紧凑版） */
.supplement-example {
  position: relative;
  background: rgba(255, 255, 255, 0.05);
  backdrop-filter: blur(10px);
  padding: 12px 16px 12px 20px;
  margin: 16px 0;
  border-radius: 0 8px 8px 0;
  font-size: 25px !important;
  line-height: 1.6 !important;
  color: #d1d5db;
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
  /* 例子用 Loli；不想要就删掉这一行 */
  font-family: 'Loli Font', var(--font-family);
}

/* 彩虹左边框：一眼区分「补充例子」与正文 */
.supplement-example::before {
  content: "";
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
  border-radius: 8px 0 0 8px;
  background: linear-gradient(180deg,
    #ff4d4d 0%, #ff9f43 25%, #ffd93d 50%, #34d399 75%, #3b82f6 100%);
}

/* 历史 / 哲学 / 经济：靠 emoji 区分，不再占一条分类色 */
.supplement-history,
.supplement-philosophy,
.supplement-economics {
  border-left: none;
}

/* 处理连续例子卡片，防止粘连 */
.supplement-example + .supplement-example {
  margin-top: 24px; /* 连续卡片时，把上边距拉大 */
}

.supplement-example strong { color: #ffffff; }

/* 全局字号、间距与行高 */
body, p, li, h1, h2, h3, h4, h5, h6 {
  font-size: 29px !important;
  line-height: 1.8 !important;
}

/* 正文小标题：调大以拉开层级（正文 29px 不变）
   注意：图谱 Tab 的 .graph-block > h2 特异性更高（0,0,2），不受本规则影响 */
h2 {
  font-size: 42px !important;
  line-height: 1.45 !important;
  margin: 2.2em 0 0.9em;
  padding-left: 0.55em;
  border-left: 5px solid var(--theme-color-3);
}
h3 {
  font-size: 36px !important;
  line-height: 1.5 !important;
  margin: 1.8em 0 0.7em;
}

body {
  padding: 2rem 0.5rem;
  max-width: none;
  margin: 0;
}

/* 句级分段：句与句贴近、段与段拉开
   （render.py 把每句输出成 <p class="sent">，段末句额外带 sent-last） */
p { margin-bottom: 1.2em; }
p.sent { margin: 0 0 0.45em; }
p.sent.sent-last { margin-bottom: 1.5em; }

/* 全站主字体：汉仪学者 */
@font-face {
  font-family: 'Hanyi Scholar';
  src: url('assets/fonts/hanyi.woff2') format('woff2');
  font-display: swap;
}
/* 装饰字体：术语用 Loli，例子用 WangTianxi（可随时撤回，见第 7 节） */
@font-face {
  font-family: 'Loli Font';
  src: url('assets/fonts/loli.woff2') format('woff2');
  font-display: swap;
}
@font-face {
  font-family: 'WangTianxi XK';
  src: url('assets/fonts/wangtianxi.woff2') format('woff2');
  font-display: swap;
}

/* 共用：提示框骨架 */
.term { position: relative; display: inline-block; cursor: help; }
.term::before {
  content: attr(data-tooltip);
  position: absolute; bottom: calc(100% + 8px); left: 50%; transform: translateX(-50%);
  background-color: #125ed9; color: #cdf40b; padding: 8px 12px; border-radius: 10px;
  font-size: 22px !important; line-height: 1.5 !important;
  width: max-content; max-width: 350px; white-space: normal; word-wrap: break-word;
  text-align: center; z-index: 1000; pointer-events: none; transition: opacity 0.2s ease; opacity: 0;
  box-shadow: 0 4px 12px rgba(0,0,0,0.3);
  font-family: system-ui, -apple-system, sans-serif;
}
.term::after {
  content: ''; position: absolute; bottom: 100%; left: 50%; transform: translateX(-50%);
  border-color: #125ed9 transparent transparent transparent; border-width: 6px; border-style: solid;
  z-index: 1000; pointer-events: none; transition: opacity 0.2s ease; opacity: 0;
}
.term:hover::before, .term:hover::after { opacity: 1; }

@keyframes theme-fade-in { 0% { opacity: 0; } 100% { opacity: 1; } }
```

## 2. 底：深空紫

```css
body[data-theme="1"] {
  --font-family: 'Hanyi Scholar', serif;
  /* 三层叠加：顶部冷光晕 + 底部暗影 + 基底渐变，制造纵深 */
  --theme-bg:
    radial-gradient(ellipse 75% 50% at 50% -10%,
      rgba(130, 155, 235, 0.30) 0%, rgba(130, 155, 235, 0) 60%),
    radial-gradient(ellipse 85% 65% at 50% 112%,
      rgba(0, 0, 0, 0.82) 0%, rgba(0, 0, 0, 0) 70%),
    linear-gradient(to bottom, #232338 0%, #0a0a12 100%);
  /* UI 主色（Tab、目录 hover、边框等）仍用冷色系 */
  --theme-color-1: #3BDFF6; --theme-color-2: #3BB1F6; --theme-color-3: #3B82F6;
  --theme-color-4: #3B53F6; --theme-color-5: #513BF6;
  --theme-animation: theme-fade-in 0.2s ease-out both;
}
html[data-theme="1"], body[data-theme="1"] { background: var(--theme-bg); }
body[data-theme="1"] {
  background-attachment: fixed;
  color: #d1d5db;
  font-family: var(--font-family);
  -webkit-font-smoothing: antialiased;
  animation: var(--theme-animation);
}
body[data-theme="1"] h1, body[data-theme="1"] h2,
body[data-theme="1"] h3, body[data-theme="1"] h4 {
  color: #ffffff;
}
```

## 3. 术语五色（高对比暖色板）

> 术语的文字色与下划线取这一组。原「黄青晨光 / 粉米柔光」套装里的蓝 `#0000ff`、靛 `#4b0082`
> 在深空紫底上对比度不足 3:1（2.3:1 / 1.6:1），已替换为绿 `#34d399`（8:1）。

```css
:root {
  --term-c1: #ff5a5a;   /* 红   5.0:1 */
  --term-c2: #ff9f43;   /* 橙   7.5:1 */
  --term-c3: #ffd93d;   /* 黄   11:1  */
  --term-c4: #a78bfa;   /* 紫   5.5:1 */
  --term-c5: #34d399;   /* 绿   8:1   */
}
```

## 4. 词条五色映射

```css
/* 术语下划线：暖色渐变彩条 */
.term {
  border-bottom: none;
  padding-bottom: 1px;
  background-image: linear-gradient(90deg, var(--term-c1), var(--term-c5));
  background-repeat: no-repeat;
  background-position: 0 100%;
  background-size: 100% 2px;
  transition: background-size 0.15s ease;
  /* 术语用 WangTianxi；不想要就删掉这一行 */
  font-family: 'WangTianxi XK', var(--font-family);
  /* 补偿装饰字体的视觉偏小：放大 + 基线微调，line-height:1 防止撑高行距 */
  font-size: 1.3em;
  line-height: 1;
  vertical-align: -0.02em;
}
.term:hover { background-size: 100% 4px; }
.term-type-1 { color: var(--term-c1); }
.term-type-2 { color: var(--term-c2); }
.term-type-3 { color: var(--term-c3); }
.term-type-4 { color: var(--term-c4); }
.term-type-5 { color: var(--term-c5); }
```
