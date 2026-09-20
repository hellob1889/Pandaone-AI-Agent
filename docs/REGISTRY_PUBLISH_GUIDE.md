# 官方 MCP Registry 发布指南（需要用户授权）

> 本指南面向 **modelcontextprotocol/registry**（Anthropic 官方）
> 由于发布需要 GitHub OAuth 设备码登录，本文档列出已准备的所有物料 + 用户需要执行的命令

---

## 已完成的准备

### 1. `server.json` 已创建

路径：[docs/registry_server.json](computer://d:\绿联云办公\项目 水龙头项目 CodeAudit_项目文档\docs\registry_server.json)

内容（核心字段）：

```json
{
  "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
  "name": "io.github.hellob1889/pandaone",
  "title": "Pandaone Guard",
  "description": "...",
  "repository": {
    "url": "https://github.com/hellob1889/Pandaone-AI-Agent",
    "source": "github"
  },
  "version": "0.7.14",
  "packages": [{
    "registryType": "pypi",
    "identifier": "pandaone-guard",
    "version": "0.7.14",
    "transport": {"type": "stdio"}
  }]
}
```

### 2. README.md 需要修改

为通过 PyPI 所有权验证，需在 Pandaone README 顶部加一行 HTML 注释：

```markdown
<!-- mcp-name: io.github.hellob1889/pandaone -->
```

**修改方案**：开 PR（PR 标题：`docs(readme): add mcp-name for official MCP registry verification`）
PR 内容已在草稿中（详见下方 PR 模板章节）

---

## 用户需要执行的命令

### Step 1: 等 README PR 合并

PR 合并后，PyPI 会自动从 README 抓取 `mcp-name` 字段

### Step 2: 安装 mcp-publisher CLI

**Windows**：
```powershell
$arch = if ([System.Runtime.InteropServices.RuntimeInformation]::ProcessArchitecture -eq "Arm64") { "arm64" } else { "amd64" }; Invoke-WebRequest -Uri "https://github.com/modelcontextprotocol/registry/releases/latest/download/mcp-publisher_windows_$arch.tar.gz" -OutFile "mcp-publisher.tar.gz"; tar xf mcp-publisher.tar.gz mcp-publisher.exe; rm mcp-publisher.tar.gz
```

**macOS**：
```bash
curl -L "https://github.com/modelcontextprotocol/registry/releases/latest/download/mcp-publisher_$(uname -s | tr '[:upper:]' '[:lower:]')_$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/').tar.gz" | tar xz mcp-publisher && sudo mv mcp-publisher /usr/local/bin/
```

### Step 3: 登录 GitHub OAuth

```bash
mcp-publisher login github
```

会输出：
```
Logging in with github...

To authenticate, please:
1. Go to: https://github.com/login/device
2. Enter code: ABCD-1234
3. Authorize this application
Waiting for authorization...
```

**用户操作**：浏览器打开 GitHub 链接，输入 8 位授权码，授权。

### Step 4: 验证 server.json

```bash
mcp-publisher validate
```

### Step 5: 发布

```bash
mcp-publisher publish
```

成功后：
```
✓ Successfully published
  Server io.github.hellob1889/pandaone version 0.7.14
```

---

## 对抗式审查：风险点

1. **PR 合并必须先发生**：README 没有 `mcp-name` 标签时，`mcp-publisher validate` 会失败 — "Registry validation failed for package"
2. **PyPI 包名大小写敏感**：`pandaone-guard` 必须和 PyPI 上的完全一致
3. **GitHub OAuth 权限范围**：mcp-publisher 需要 GitHub repo:public_content 权限
4. **PR 自动创建**：publish 命令会直接开 PR 到 modelcontextprotocol/registry，需要 maintainer 批准

---

## PR 模板（用户手动开 PR 或让 agent 代开）

**Branch 名称**：`add-mcp-name-for-registry`
**PR 标题**：`docs(readme): add mcp-name HTML comment for official MCP registry verification`
**PR 内容**：

```markdown
## Add mcp-name for MCP Registry verification

Adding `<!-- mcp-name: io.github.hellob1889/pandaone -->` to README.md so that
the official MCP Registry can verify PyPI package ownership when publishing
this server.

### Why
The [official MCP Registry](https://github.com/modelcontextprotocol/registry)
requires PyPI packages to declare their MCP name in the package README
(via HTML comment or visible text). This is documented at
[Package Types → PyPI](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/package-types.mdx#pypi-packages).

### Change
One HTML comment line added near the top of `README.md` (after the banner):

```markdown
<!-- mcp-name: io.github.hellob1889/pandaone -->
```

The token is wrapped in `<!-- … -->` so it renders invisibly on GitHub and PyPI,
and the mcp-name is followed by the standard comment-close boundary.

### Verification
After merge:
1. The PyPI `pandaone-guard` README will include `mcp-name: io.github.hellob1889/pandaone`
2. `mcp-publisher validate` will pass ownership check
3. `mcp-publisher publish` will open a PR to modelcontextprotocol/registry
```

---

## 备注：为什么不直接代发？

GitHub OAuth 设备码授权是单向的 — 用户必须手动在浏览器里 approve。
我无法替用户授权。

但 PR 可以代开，命令可以列出来。打开 [`docs/registry_server.json`](registry_server.json) 与本文档后，用户可以按部就班完成整个流程。

时间预估：
- 开 PR：1 分钟
- PR 合并：1-3 分钟（自动化 review）
- 安装 CLI：30 秒
- OAuth 登录：30 秒（用户操作）
- publish：1 分钟

总耗时：~5 分钟