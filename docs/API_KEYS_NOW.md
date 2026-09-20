# Pandaone 推广 - 用户需要的最后 3 步（30 秒）

## 现状（自动完成 + 阻塞）

✅ 已完成：
- Glama.ai 提交
- GitHub 仓库 SEO（19 topics + 描述）
- 3 处 awesome-mcp-servers PR
- Pandaone README 注册 mcp-name
- 11 个平台发布草稿 / 表单数据
- dev.to 用 hellob1889 GitHub 账号创建并登录

❌ 阻塞：
- dev.to Settings/Extensions 页面在新账号下渲染失败（Forem SPA bug）
- Hashnode / Reddit 未登录

## 你 30 秒能解锁的事

### A. dev.to API key（解锁 dev.to 自动发布）

1. 在已经打开的 Chrome 标签页里，**关掉那个 dev.to Settings 标签页**，重新打开一个新标签。
2. 直接访问：**`https://dev.to/settings/extensions`**
3. 滚到页面底部，找到 **"Generate API key"** 按钮（页面可能错位，可能在底部）
4. 描述填 "Pandaone 发布"，点生成
5. 复制生成的 key（形如 `xxxx1234abcd...`），粘贴发给我

### B. Hashnode Personal Access Token（解锁 Hashnode 自动发布）

1. 访问：**`https://hashnode.com/`**
2. 用 GitHub 登录（你已经知道怎么点了）
3. 进 Settings → Developer → Generate Token
4. 复制 token，发给我

### C. Reddit API credentials（解锁 Reddit 3 个 subreddit 发布）

1. 访问：**`https://www.reddit.com/prefs/apps`**
2. 滚到底部 "Create another app"
3. name: `PandaonePublish`, app type: `script`
4. redirect uri: `http://localhost:8080`（占位）
5. 创建后复制 client_id 和 secret，发给我

## 我收到后立刻做什么

- **dev.to**：直接 POST `https://dev.to/api/articles` 发布已写好的 Pandaone 审计文章
- **Hashnode**：GraphQL `publishPost` mutation 发布 Pandaone 教程
- **Reddit**：用 PRAW/curl OAuth2 token → POST 到 r/ClaudeAI、r/MCP、r/LocalLLaMA

每个平台 30 秒内完成发布，总共 5 分钟搞定。

## 不需要 API key 的平台（可以现在就推进）

**掘金 / 知乎** — 浏览器自动化发布
**Product Hunt** — GraphQL API（需要 developer token，从 `https://www.producthunt.com/v2/oauth/applications` 创建）
**cursor.directory** — 已阻塞 OAuth state
**HN Show HN** — 网络不可达（ERR_TIMED_OUT）

## 你给 3 个 key 后我的 5 分钟执行清单

1. dev.to POST `/api/articles`（30s）
2. Hashnode GraphQL publishPost（30s）
3. Reddit OAuth + 3 个 subreddit post（2min）
4. 掘金 mcp_Computer_Use（如果你接管登录，1min）
5. 知乎 mcp_Computer_Use（如果你接管登录，1min）
6. Product Hunt（如能给 developer token，1min）

总计：拿到 key 后 5 分钟，6+ 平台发布完成。

---

**你能 30 秒搞定 A/B/C 任一个，就能立刻解锁对应的自动发布。**

最低门槛：A 一个，dev.to 就能发布，B/C 跟着解锁。
