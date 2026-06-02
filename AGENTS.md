# AGENTS.md — 最后的DBA (lastdba.com)

为 AI coding agent 准备的工程指引。读完此文件即可独立完成该博客项目的开发维护工作。

## 项目概览

- **博客名**: 最后的DBA
- **域名**: https://lastdba.com
- **作者**: liuzhilong62
- **技术栈**: Hugo 0.161.1 + Blowfish 主题 (Git submodule)
- **托管**: GitHub Pages + Cloudflare CDN (橙色云 🧡)
- **本地编辑**: Typora (macOS) + PicGo (图片上传)
- **内容**: 80+ 篇 PostgreSQL 技术文章，中文写作
- **多语言**: 2026-06 启用英文版 (lastdba.com/en/)。中文为默认语言，英文内容 `.en.md` 后缀
- **目录**: `/Users/liuzhilong62/Documents/01-mygithub/blogs`

## 目录结构

```
blogs/
├── hugo.yaml                  # 核心 Hugo 配置
├── config/_default/
│   ├── params.yaml            # Blowfish 主题参数（共享）
│   ├── languages.zh.yaml      # 中文语言配置 + 精选文章 + 社交链接
│   ├── languages.en.yaml      # 英文语言配置 + 精选文章 + 社交链接
│   ├── menus.zh.yaml          # 中文导航菜单
│   └── menus.en.yaml          # 英文导航菜单
├── content/
│   ├── _index.md              # 首页 (profile layout + 统计短代码)
│   ├── about/index.md         # 关于页
│   └── posts/
│       ├── PostgreSQL案例/     # 22 篇
│       ├── PostgreSQL内功修炼/  # 15 篇
│       ├── PostgreSQL源码解析/  # 5 篇
│       ├── PostgreSQL面试题/    # 1 篇
│       ├── 论文解读/            # 4 篇
│       ├── 读书笔记/            # 15 篇
│       ├── AIOps/              # 1 篇
│       └── 杂项/               # 14 篇 (年终总结等)
├── assets/
│   ├── css/custom.css         # 自定义样式 (当前为空, 尽量不用)
│   ├── icons/csdn.svg         # CSDN 自定义图标
│   ├── icons/modb.svg         # 墨天轮自定义图标
│   └── img/avatar.jpg         # 头像
├── static/
│   ├── CNAME                  # lastdba.com (防止 GitHub Pages 重置)
│   ├── favicon.ico / favicon-*.png / apple-touch-icon.png
│   └── img/                   # 文章图片 (764 张, 251MB)
│       └── csdn/              # 从 CSDN 下载的防盗链图片 (gitignored)
├── layouts/                   # 自定义模板覆盖 (见下文清单)
├── scripts/                   # 辅助脚本 (当前为空)
├── themes/blowfish/           # Git submodule
├── .github/workflows/
│   └── hugo.yml               # Hugo 部署
└── AGENTS.md                  # 本文件
```

## 核心命令

```bash
# 本地开发
hugo server -D --bind 0.0.0.0 --port 1313

# 构建 (CI 用 --minify, 本地可省略)
hugo --minify

# 创建新文章 (单文件格式, 与现有 78 篇一致)
hugo new posts/PostgreSQL案例/my-new-post.md

# 部署 (编辑完成后自动执行)
hugo --quiet && git add -A && git commit -m "描述" && git push
```

**push 即部署**: GitHub Actions 自动触发 hugo.yml, ~1 分钟后刷新到 lastdba.com。

## 多语言发布工作流 (Multilingual Publishing)

博客支持中英双语。中文为默认语言，英文内容使用 `.en.md` 后缀。

### 写新文章时同时发布中英文

```bash
# 1. 创建中文文章
hugo new posts/分类目录/slug.md
# 编辑中文内容...

# 2. 在同目录创建英文翻译（注意 .en.md 后缀）
cat > content/posts/分类目录/slug.en.md
# 编辑英文内容...

# 3. 构建 + 提交
hugo --quiet && git add -A && git commit -m "post: 标题" && git push
```

### 翻译已有中文文章

```bash
# 中文原文: content/posts/分类/文章.md
# 创建翻译: content/posts/分类/文章.en.md
# Hugo 通过文件名 stem 自动关联两个版本
```

### 验证发布结果

- **中文**: https://lastdba.com/2026/06/01/slug/
- **英文**: https://lastdba.com/en/2026/06/01/slug/
- **llms.txt 中文**: https://lastdba.com/llms.txt（81 篇）
- **llms.txt 英文**: https://lastdba.com/en/llms.txt（63 篇）

### 注意事项

- 中文 frontmatter 和英文 frontmatter 各写各的（title/description 各自语言）
- `categories` 和 `tags` 在英文文章中必须使用英文翻译值，中文文章保留中文。Hugo taxonomy 按值分离，中英文各自有独立的分类体系。
- 代码块、SQL、图片路径中英文版本完全一致，不要改动
- ~~英文文章末尾加 originally published 声明~~（已全部删除，不再需要）
- **精选文章 (featured)**: 配置在 `languages.zh.yaml` / `languages.en.yaml` 的 `params.homepage.featuredArticles`，**不在**共享 `params.yaml` 中。中英文各写各的标题，保持两边文章对应一致。Hugo 按语言自动选用对应列表。

## 写文章工作流

### 1. 创建文章

```bash
hugo new posts/分类目录/slug.md
```

文章放在对应分类的子目录下，使用单 `.md` 文件格式（与现有 78 篇一致）。

### 2. 编辑内容

用 Typora 编辑。遵循写作规范：

```
# 问题现象
...现象描述...

# 问题分析
...分析过程...

## 源码分析
...代码块 + 解释...

## 测试验证
...测试结果...

# 总结
...要点总结...
```

- 代码块必须指定语言: ` ```sql `, ` ```shell `, ` ```c `
- 短句为主, 口语化技术中文 (如 "库挂了" 而非 "数据库实例异常终止")
- 标题用 `##` 起步 (h1 是文章标题, TOC 不渲染 h1)

### 3. 插入图片 (PicGo + Typora)

**重要**: Typora macOS 版会写绝对路径, 这是已知问题。图片插入流程:

1. Typora 中粘贴图片 → PicGo 自动上传到 GitHub
2. PicGo 生成 `https://raw.githubusercontent.com/liuzhilong62/blogs/main/static/img/xxx.png`
3. Hugo render hook (`layouts/_default/_markup/render-image.html`) 构建时自动转换为 `/img/xxx.png`

**不要手动修改图片路径**。render hook 处理一切。

PicGo 配置 (参考, 不要改动):
- 仓库: `liuzhilong62/blogs`
- 分支: `main`
- 路径: `static/img/`
- customUrl: 空 (使用 raw GitHub URL)

### 4. 发布

```bash
hugo --quiet && git add -A && git commit -m "post: 标题" && git push
```

**不要等用户说 "继续"** — 编辑完文件后直接 push。push 触发 CI 自动部署。

## Frontmatter 规范

```yaml
---
title: "文章标题"
date: 2026-05-18
draft: false
categories: ["PostgreSQL案例"]
tags: ["PostgreSQL", "性能", "索引"]
description: "20-60 字的中文摘要，用于首页卡片和搜索结果"
showHero: false
---
```

- `categories`: 必须是以下之一 —
  中文: `PostgreSQL案例`, `PostgreSQL内功修炼`, `PostgreSQL源码解析`, `PostgreSQL面试题`, `论文解读`, `读书笔记`, `AIOps`, `杂项`
  英文: `PostgreSQL Cases`, `PostgreSQL Internals`, `PostgreSQL Source Code`, `PostgreSQL Interview Questions`, `Paper Reviews`, `Reading Notes`, `AIOps`, `Miscellaneous`
- `description`: 必填, 20-60 字中文。用于首页卡片 (card.html) 和分类页 (simple.html) 的摘要显示
- `showHero`: 默认 false。hero 背景被用户否决过, 不要开启
- `draft: true` 的文章不会发布, 但 `hugo server -D` 本地可见

## 配置速查

### hugo.yaml 关键项
- `baseURL: "https://lastdba.com/"` — 改域名时改这里
- `hasCJKLanguage: true` — 中文优化
- `summaryLength: 80` — 自动摘要长度
- `pagination.pagerSize: 10` — 每页 10 篇文章
- `params.readingTime: 300` — 中文阅读速度 (字/分钟)
- `markup.goldmark.renderer.unsafe: true` — 允许文章内嵌 HTML
- `permalinks.posts: "/:year/:month/:day/:slug/"` — Jekyll 兼容 URL 格式
- `mainSections: ["posts"]` — 告诉 Hugo 内容是 posts/

### params.yaml 关键项
- `colorScheme: "ocean"` — 主题配色
- `homepage.layout: "profile"` — 首页布局 (hero 布局被拒绝过)
- `article.showHero: false` — 文章不显示 hero 图
- `article.showWordCount: true` — 显示字数 (中文不准但大致可用)
- `footer.showLicense: true` — 底部显示 CC BY-NC-SA 4.0
- `footer.showThemeAttribution: false` — 不显示 Blowfish 版权
- `featuredArticles` **不在此文件** — 精选文章列表已移至各语言 config（`languages.zh.yaml` / `languages.en.yaml`），确保中英文各用自己的标题

## 自定义 Layout 清单

以下文件覆盖了 Blowfish 默认模板，修改前务必理解其用途:

| 文件 | 用途 |
|------|------|
| `layouts/_default/rss.xml` | **RSS 全文输出** — 添加 `<content:encoded>` 供 agent 和 RSS 阅读器消费 |
| `layouts/index.llms.txt` | **AI agent 站点地图** — 纯文本文章索引 (按分类)，供 agent 快速发现 |
| `layouts/index.llmsfull.txt` | **AI agent 全文** — 全站 Markdown 原文，供 agent 一次性摄入 |
| `layouts/_default/_markup/render-image.html` | **图片路径转换** — PicGo raw URL → `/img/`, Typora 本地路径 → `/img/` |
| `layouts/partials/custom-head.html` | favicon 多重声明 (覆盖 Blowfish 默认鱼图标) |
| `layouts/partials/article-link/card.html` | 首页文章卡片 — 用 `description` 替代自动摘要 |
| `layouts/partials/article-link/simple.html` | 分类页文章列表 — 用 `description` 替代自动摘要 |
| `layouts/partials/home/profile.html` | 首页 profile 区域 (可能有定制) |
| `layouts/partials/home/featured.html` | 精选文章区域 |
| `layouts/partials/header/components/desktop-menu.html` | 桌面端导航菜单 |
| `layouts/shortcodes/article-count.html` | 短代码 — 动态统计文章总数 |
| `layouts/shortcodes/category-count.html` | 短代码 — 动态统计分类总数 |

## 图片处理铁律

1. **图片路径不要手动改** — render hook 自动处理所有转换
2. **CSDN 防盗链图片** — 已全部下载到 `static/img/csdn/` 并替换了 markdown 中的 URL。该目录在 `.gitignore` 中
3. **图片压缩** — 当前 764 张图 251MB。新增图片前应考虑压缩
4. **Chrome 缓存** — 图片更新后如果用户说 "还是看不到", 先让用户硬刷新 (Cmd+Shift+R) 或开隐身窗口。十有八九是 Chrome 缓存了旧的 404

## 部署与 DNS

- **GitHub Actions**: `.github/workflows/hugo.yml`
- **Cloudflare**: DNS 橙色云 🧡 proxy 模式, 亚太节点加速中国访问
- **CNAME**: `static/CNAME` 文件包含 `lastdba.com`, 必须在每次部署的 `public/` 中存在, 防止 GitHub Pages 重置自定义域名
- **Pages 设置**: Source → "GitHub Actions"

## 设计原则

- **极简风格** — 博客追求简约干净的阅读体验。不要建议添加装饰性图片、背景图案、UI 花活
- **优先 Blowfish 原生样式** — 能用框架自带功能解决的问题不加自定义 CSS。不要用 CSS 重复造轮子
- **不要加卡片边框/阴影/渐变** — 用户明确拒绝
- **不要用 hero layout** — 已尝试并被拒
- **自定义 CSS 只用于无法避免的场景** — 如页面背景装饰, 且用 `body::before` 不影响深色模式
- **视觉改动一次只展示一个方案** — 用户说"丑"或"不搭"就直接放弃该方向
- **CSS 选择器不要目标 Blowfish 内部 DOM** — `<sectionheader>` 等选择器静默失败
- **修改后先 browser_navigate 验证** — 不要直接让用户检查

## 常见踩坑

1. **Typora 写绝对路径** — macOS 版 Typora 无视相对路径设置, 写 `/Users/.../static/img/xxx.png`。render hook 处理一部分, 但首选 PicGo 粘贴
2. **Hugo 版本** — 必须 0.158.0+, CI 固定 0.161.1. `brew install hugo` 默认最新版, 本地开发前确认版本
3. **Submodule** — Blowfish 是 git submodule, clone 时需要 `--recurse-submodules`
4. **YAML 菜单** — Blowfish 的 dropdown 子菜单在 YAML 下不可用, 全部用 flat menu
5. **markdown 与 HTML 混写** — goldmark 会剥离 `<div>`, HTML 块必须纯 HTML (不用 `---`, `###` 等 markdown 分隔符)
6. **favicon** — 需要同时覆盖 `favicon.ico`, `favicon-32x32.png`, `favicon-16x16.png`, 否则 Blowfish 默认鱼图标复现
7. **hugo build lock** — `.hugo_build.lock` 已在 `.gitignore`, 不要提交
8. **`.DS_Store`** — 已在 `.gitignore`, macOS 下 `git add -A` 会自动跳过
