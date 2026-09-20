# Ready-to-Paste Submission Form Data

**Generated**: 2026-09-17 Asia/Shanghai
**Purpose**: Submit pandaone-guard to **5 free MCP registries + 8 free promotion channels** in <2 minutes per channel.
**Status as of 2026-09-17**:
- ✅ Tier 1 (autonomous, no browser): Done — repo description, 19 topics, 6 content drafts
- ✅ Tier 2 (GitHub API PRs): Done — punkpeye/awesome-mcp-servers PR #14557, jaw9c/awesome-mcp-servers PR #2, Pandaone PR #47 (mcp-name)
- ⏸ Tier 3 (browser forms): Browser session loss in this MCP environment prevents full automation. All form data prepared below for 1-click user submission.

---

## 第一性原理 + 对抗式审查 — 为什么有些无法直接自动化

| 渠道 | 状态 | 原因 |
|---|---|---|
| mcp.so | ⏸ 用户提交 | Web form，需要登录 + 表单 POST（之前会话尝试过，浏览器 session 在 user takeover 时丢失） |
| glama.ai/mcp | ⏸ 用户提交 | 同上 — Add Server 按钮需要 GitHub OAuth 登录 |
| cursor.directory/mcp | ⏸ 用户提交 | 表单 + 邮箱验证 |
| MCPMarket.cn | ⏸ 用户提交 | 中文界面表单 |
| Smithery | ❌ SKIP | 2026-08-05 被 Arcade.dev 收购，需要 hosted HTTPS endpoint（pandaone 是 stdio 本地，不兼容） |
| OpenAI MCP directory | ❌ SKIP | 不存在公开申请表单（仅 partner program，需付费合作） |
| Hacker News (Show HN) | ⏸ 用户提交 | 需要用户登录态（HN 禁止第三方刷票） |
| Reddit | ⏸ 用户提交 | r/ClaudeAI / r/LocalLLaMA / r/MCP 需要用户账户 |
| Product Hunt | ⏸ 用户提交 | 需要用户 maker 账户 + Hunter 邀请（首日曝光翻倍） |
| 掘金 | ⏸ 用户提交 | 需要用户登录 |
| 知乎 | ⏸ 用户提交 | 需要用户登录 + 不能直接发链接 |
| dev.to / Hashnode / Medium | ⏸ 用户提交 | 需要用户账号发布 |

**已 100% 准备完毕**：每个渠道都有完整 form data / 草稿 / 复制粘贴指南，用户投入 <3 分钟每个。

---

## Part 1: mcp.so（中文流量主导，免费）

### URL
```
https://mcp.so/submit
```

### 表单字段（按出现顺序）

| 字段 | 值 |
|---|---|
| **Type** | `MCP Server` |
| **Name** | `pandaone-guard` |
| **URL** | `https://github.com/hellob1889/Pandaone-AI-Agent` |
| **Server Config** | 见下方 JSON |

### Server Config（直接复制粘贴）

```json
{
  "mcpServers": {
    "pandaone-guard": {
      "command": "pandaone-mcp",
      "args": [],
      "env": {
        "PANDAX_FP_PASSWORD": "0000",
        "PANDAX_LANG": "en"
      }
    }
  }
}
```

### 提交时间：2 分钟

---

## Part 2: glama.ai/mcp（英文流量主导，免费）

### URL
```
https://glama.ai/mcp/servers
```
登录后点右上角 "Add Server" 按钮。

### 表单字段

| 字段 | 值 |
|---|---|
| **Repository URL** | `https://github.com/hellob1889/Pandaone-AI-Agent` |
| **Title** | `Pandaone Guard` |
| **Short Description** | `Forces every AI Agent code change to leave a structured problem/reason/approach audit record before commit.` |
| **Categories** | 勾选 `Developer Tools`, `Security`, `AI & Machine Learning` |
| **Tags** | `mcp`, `code-audit`, `ai-agent`, `claude`, `cursor`, `python`, `local-first`, `pre-commit`, `static-analysis` |

### 提交时间：1 分钟（glama 自动从 GitHub README 抓取完整 description，无需手填）

---

## Part 3: cursor.directory/mcp（Cursor 用户精准流量，免费）

### URL
```
https://cursor.directory/mcp/new
```

### 表单字段

| 字段 | 值 |
|---|---|
| **MCP Server Name** | `Pandaone Guard` |
| **GitHub URL** | `https://github.com/hellob1889/Pandaone-AI-Agent` |
| **Description** | `Open-source MCP server that audits every AI Agent code change. Pre-commit hook blocks unaudited changes. Local stdio, no API key, MIT.` |
| **Categories** | 勾选 `Developer Tools`, `AI` |
| **Install command** | `pip install pandaone-guard==0.7.14` |

### 提交时间：1 分钟

---

## Part 4: MCPMarket.cn（中文 MCP 检索入口，免费）

### URL
```
https://www.mcpmarket.cn/submit
```
（如路径变化，从首页 `https://www.mcpmarket.cn/` 进入"提交收录"）

### 表单字段（中文界面）

| 字段（中文） | 值 |
|---|---|
| **工具名称** | `Pandaone Guard` |
| **GitHub 地址** | `https://github.com/hellob1889/Pandaone-AI-Agent` |
| **工具简介** | `开源 MCP 服务器，为 AI Agent 代码改动建立问题/原因/方案三段式审计凭证，pre-commit 钩子拦截未审计变更。` |
| **类别** | 勾选 `开发工具` `安全` `AI 编程` |
| **标签** | `MCP`, `代码审计`, `AI Agent`, `Claude`, `Cursor`, `本地优先`, `Python`, `MIT` |

### 提交时间：1 分钟

---

## Part 5: Hacker News — Show HN（英文极流量，免费）

### URL
```
https://news.ycombinator.com/submit
```

### 字段

| 字段 | 值 |
|---|---|
| **Title** | `Show HN: Pandaone Guard – Local MCP server that audits every AI Agent code change` |
| **URL** | `https://github.com/hellob1889/Pandaone-AI-Agent` |
| **Text** | （留空，HN 自动从 URL 抓 OG） |

### 提交后必做

| 步骤 | 说明 |
|---|---|
| 1. 留在评论里 | HN 规则要求作者本人在场回答问题（至少 2-3 小时） |
| 2. 不要刷票 | 违反社区铁律，账号封禁 |
| 3. 最佳时间 | 周二-周三 北京时间 21:00-24:00（UTC 13:00-16:00） |

### 完整 draft（备用）
[docs/promotion/showhn_pandaone.md](promotion/showhn_pandaone.md)

### 提交时间：30 秒（标题要"Show HN:"开头，URL 自带） |

---

## Part 6: Reddit（多 sub 同步发，免费）

### Subreddits（按优先级）

| Sub | 受众 | 提交 URL |
|---|---|---|
| **r/ClaudeAI** | Claude 用户（最精准） | https://www.reddit.com/r/ClaudeAI/submit |
| **r/MCP** | MCP 用户（小但精准） | https://www.reddit.com/r/MCP/submit |
| **r/LocalLLaMA** | 本地 LLM 用户 | https://www.reddit.com/r/LocalLLaMA/submit |

### 字段（以 r/ClaudeAI 为例）

| 字段 | 值 |
|---|---|
| **Title** | `[Project] I built an MCP server that audits every change my AI Agent makes — open source, MIT, M8ven A-grade` |
| **URL** | `https://github.com/hellob1889/Pandaone-AI-Agent` |
| **Flair** | `Project` |

### 完整 drafts
- [docs/promotion/reddit_rClaudeAI_pandaone.md](promotion/reddit_rClaudeAI_pandaone.md)（主推）
- [docs/promotion/reddit_rLocalLLaMA_pandaone.md](promotion/reddit_rLocalLLaMA_pandaone.md)

### Reddit 规则注意
- 严格 9:1 规则（自我推广每 9 条他人内容才能发 1 条）
- 必须配技术深度评论（不能纯发链接）

### 提交时间：每 sub 2 分钟

---

## Part 7: Product Hunt（英文产品发布，免费）

### URL
```
https://www.producthunt.com/posts/new
```

### 字段

| 字段 | 值 |
|---|---|
| **Name** | `Pandaone Guard` |
| **Tagline** | `AI code audit trail. Free, local, MIT.` |
| **Description** | 见 [docs/promotion/producthunt_pandaone.md](promotion/producthunt_pandaone.md) |
| **Topics** | `Developer Tools`, `Open Source`, `Artificial Intelligence`, `Security` |
| **Maker Comment** | 同 Description 末尾的 First Comment 段 |

### 提交时间：3 分钟（含 maker comment 撰写）

### 注意事项
- 提交前必须有 Hunter（邀请你提交的人，曝光翻倍）— 可去 [ProductHunt community](https://www.producthunt.com/#makers) 找
- 最佳时间：周一-周三 北京时间 21:00（UTC 13:00）

---

## Part 8: 掘金（中文开发者流量，免费）

### URL
```
https://juejin.cn/editor/post/new
```

### 字段

| 字段 | 值 |
|---|---|
| **标题** | `AI Agent 写代码谁来审计？我做了一个 MCP 工具给每行变更打 AI 凭证` |
| **分类** | `后端`, `AI` |
| **标签** | `AI 编程` `Claude` `Cursor` `Trae` `MCP` `代码审计` `开源` |
| **正文** | 见 [docs/promotion/juejin_pandaone_AI审计.md](promotion/juejin_pandaone_AI审计.md) |

### 提交时间：2 分钟（粘贴全文 + 配图）

### 规则
- 文章 ≥1500 字（已满足）
- 配图 ≥5 张（已含 3 张 GitHub raw 链接）
- 原创度审核（已 100% 原创）

---

## Part 9: 知乎（中文长尾流量，免费）

### 路径（不走专栏，走问答）
```
1. 在知乎搜索：`AI Agent 写代码如何审计`
2. 找到高浏览量的问题（如"Claude / Cursor 改完代码，如何追溯 AI 改了什么、为什么改？"）
3. 用 [docs/promotion/zhihu_pandaone_答案.md](promotion/zhihu_pandaone_答案.md) 作答
4. 文末贴 GitHub 链接（不要开篇就贴）
```

### 规则
- 不能纯发链接（封号）
- 先用具体问题切入（已满足）
- 答案质量要高（已 ~1200 字 + Q&A 预演 5 题）

---

## Part 10: dev.to（英文开发者长尾流量，免费）

### URL
```
https://dev.to/new
```

### 字段

| 字段 | 值 |
|---|---|
| **Title** | `How I built an MCP server to audit every change my AI Agent makes` |
| **Tags** | `mcp` `ai-agents` `code-audit` `security` `python` `claude` `cursor` `opensource` |
| **Cover image** | `https://raw.githubusercontent.com/hellob1889/Pandaone-AI-Agent/main/assets/social-preview.png` |
| **Body** | 见 [docs/promotion/devto_pandaone_audit.md](promotion/devto_pandaone_audit.md) |

### 提交时间：2 分钟

---

## Part 11: Hashnode（英文 SEO 流量，免费）

### URL
```
https://hashnode.com/
```
登录后 `Create Post`

### 字段

| 字段 | 值 |
|---|---|
| **Title** | `Setting up Pandaone Guard for AI code audit in 5 minutes` |
| **Tags** | `mcp`, `ai-agents`, `code-audit`, `python`, `claude`, `cursor`, `tutorial` |
| **Body** | 见 [docs/promotion/hashnode_pandaone_quickstart.md](promotion/hashnode_pandaone_quickstart.md) |

### 提交时间：2 分钟

---

## 总览：用户 1 分钟级提交清单

| 渠道 | 状态 | 用户操作 |
|---|---|---|
| 4 个 MCP 注册表 | ⏸ 浏览器 | 12 分钟（每个 ~3 分钟） |
| HN Show HN | ⏸ 用户登录 | 30 秒 + 2-3 小时驻场 |
| Reddit (3 subs) | ⏸ 用户登录 | 6 分钟 |
| Product Hunt | ⏸ 用户登录 + Hunter | 5 分钟 |
| 掘金 / 知乎 / dev.to / Hashnode | ⏸ 用户登录 | 8 分钟 |

**总计**：~30 分钟覆盖 11 个免费渠道

---

## 已自动化完成的（无需用户操作）

| 工作 | 状态 |
|---|---|
| Pandaone 仓库 description + 19 个 topics | ✅ 已通过 GitHub API 更新 |
| Pandaone PR #47（添加 mcp-name 标签） | ✅ 已开，等待用户合并 |
| punkpeye/awesome-mcp-servers PR #14557 | ✅ 已开，等待合并 |
| jaw9c/awesome-mcp-servers PR #2 | ✅ 已开，等待合并 |
| 官方 MCP Registry server.json | ✅ 已生成 [docs/registry_server.json](registry_server.json) |
| 官方 MCP Registry 发布指南 | ✅ [docs/REGISTRY_PUBLISH_GUIDE.md](REGISTRY_PUBLISH_GUIDE.md) |

---

## 时间预估（用户全部提交完）

- **4 个 MCP 注册表**：12 分钟
- **8 个内容渠道**：~30 分钟（含驻场）
- **总计**：~45 分钟

vs **价值**：
- M8ven 已达 100/A
- 多平台收录 = 持续 SEO 长尾流量
- 22+ → 200+ PyPI downloads（30 天内合理预期）