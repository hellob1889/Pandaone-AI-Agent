# API Keys — 一键生成 + 给我粘贴

> 给我这三个免费 API key（30 秒生成，零付费），就能用 API 直接发到 5 个平台，完全绕过浏览器。

---

## 1. dev.to API Key（30 秒）

**步骤**：
1. 浏览器打开 https://dev.to/settings/extensions
2. 登录你的 dev.to 账号（如无，免费注册一个，30 秒）
3. 找到 "DEV Community API Key" 区
4. 输入描述如 `pandaone-guard publish`
5. 点 "Generate API Key"
6. 复制生成的 key（形如 `xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`）

**粘贴给我**：你的 dev.to API key

---

## 2. Hashnode Personal Access Token（30 秒）

**步骤**：
1. 浏览器打开 https://hashnode.com/settings/developer
2. 登录你的 Hashnode 账号（如无，免费注册，30 秒）
3. 找到 "Personal Access Token"
4. 输入描述如 `pandaone-guard publish`
5. 选择权限：至少勾选 `publish_post`
6. 点 "Generate"
7. 复制 token（形如 `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`）

**粘贴给我**：你的 Hashnode PAT

---

## 3. Reddit API Credentials（60 秒）

**步骤**：
1. 浏览器打开 https://www.reddit.com/prefs/apps
2. 登录（如无账号，免费注册）
3. 页面底部 "create another app..." 按钮
4. 填写：
   - name: `pandaone-guard-publisher`
   - type: 选 **script**
   - redirect uri: `http://localhost:8080`（任意有效 URI 即可）
   - permissions: 留默认
5. 点 "create app"
6. 复制显示的：
   - **client_id**（app 图标下方，14 字符）
   - **secret**（"secret" 标签右边）

**粘贴给我**：
- client_id: `xxxxxxxxxxxxxx`
- secret: `xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`

---

## 安全声明

- 这三个 API key/secret **只用于发 Pandaone Guard 推广内容**
- 不会存储在任何文件里（除非你要求）
- 你可以在 https://dev.to/settings/extensions / Hashnode Settings / Reddit Apps 随时 revoke
- **不需要付费**

---

## 我用这些 key 干什么

| Key | 做什么 |
|---|---|
| dev.to | POST https://dev.to/api/articles — 发 [docs/promotion/devto_pandaone_audit.md](promotion/devto_pandaone_audit.md) |
| Hashnode | GraphQL mutation — 发 [docs/promotion/hashnode_pandaone_quickstart.md](promotion/hashnode_pandaone_quickstart.md) |
| Reddit | POST /api/submit — 发到 r/MCP / r/ClaudeAI / r/LocalLLaMA |

---

## 不需要 key 的（我自己处理）

| 平台 | 状态 |
|---|---|
| 4 个 awesome-mcp-servers PR | ✅ 已开（punkpeye #14557, jaw9c #2） |
| Pandaone 仓库 SEO | ✅ 已更新（19 topics + description） |
| Pandaone PR #47 (mcp-name) | ✅ 已开 |
| 官方 MCP Registry server.json | ✅ 已生成 |

---

## 仍需你登录的平台（key 帮不了）

| 平台 | 需要 |
|---|---|
| mcp.so | Web form + 登录 |
| glama.ai | GitHub OAuth + reCAPTCHA |
| cursor.directory/mcp | Web form + 登录 |
| MCPMarket.cn | Web form + 登录 |
| Hacker News Show HN | HN 账号（HN 禁止刷票，作者需驻场 2-3 小时） |
| Product Hunt | Maker 账户 + Hunter 邀请 |
| 掘金 | 用户账号 |
| 知乎 | 用户账号 |

这些我会准备 1-分钟复制粘贴 form data（已大部分写好在 SUBMISSION_FORM_DATA.md），你只需粘一次。

---

**粘完三个 key 直接告诉我**："dev.to: xxx, hashnode: yyy, reddit: id=zzz, secret=www"
我就开始用 API 直发，不再碰任何浏览器。