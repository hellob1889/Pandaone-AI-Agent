# MCP 集成

> **让 AI Agent（Claude / Cursor / Trae）直接调用 Pandaone AI Agent**。

## 什么是 MCP？

[MCP (Model Context Protocol)](https://modelcontextprotocol.io/) 是一个标准协议，让 AI Agent 通过 stdio JSON-RPC 调用外部工具。

Pandaone 实现为 **stdio JSON-RPC 2.0 server**——**无网络暴露**，由 IDE 管理进程生命周期。

## 客户端配置

### Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json`（macOS）
或 `%APPDATA%\Claude\claude_desktop_config.json`（Windows）：

```json
{
  "mcpServers": {
    "pandaone": {
      "command": "pandaone-mcp",
      "env": {}
    }
  }
}
```

### Cursor

`~/.cursor/mcp.json`：

```json
{
  "mcpServers": {
    "pandaone": {
      "command": "pandaone-mcp"
    }
  }
}
```

### Trae

在 Trae IDE 设置 → MCP → 添加：
```json
{
  "name": "pandaone",
  "command": "pandaone-mcp",
  "args": []
}
```

## 暴露的 12 个工具

| 工具名 | 用途 |
|---|---|
| `pandaone_init` | 在指定目录初始化 Pandaone |
| `pandaone_lock` | 锁定所有受保护扩展名的文件 |
| `pandaone_unlock` | 解除锁定 |
| `pandaone_write` | 审计写入（核心）|
| `pandaone_log` | 查询审计历史，支持 13 种导出格式 |
| `pandaone_status` | 显示项目状态仪表盘 |
| `pandaone_install_hook` | 安装 L3 pre-commit hook |
| `pandaone_watch` | 启动 watchdog 守护进程 |
| `pandaone_install_git` | 探测/安装 git |
| `pandaone_fingerprint_update` | 更新 CLI 自指纹 |
| `pandaone_ci` | L7 CI 验证（git diff vs audit log） |

## AI Agent 典型工作流

```
1. AI Agent 接到任务："实现用户登录"
2. Agent 思考：我需要写 src/auth.py
3. Agent 检查：pandaone_status → 项目已 init
4. Agent 调用：pandaone_write
   - file: "src/auth.py"
   - reason: "实现用户登录功能"
   - problem: "用户系统缺少登录入口"
   - approach: "JWT 认证 + bcrypt 密码哈希"
5. Agent 提交：git add + git commit（hook 自动校验）
6. Agent 推送：git push（CI 自动验证）
```

## 手动测试 MCP

```bash
# 启动 MCP server
pandaone-mcp

# 在另一个终端发送 JSON-RPC 请求
echo '{"jsonrpc":"2.0","method":"initialize","params":{"clientInfo":{"name":"test"}},"id":1}' | pandaone-mcp
```

返回：
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2024-11-05",
    "serverInfo": {"name": "pandaone", "version": "0.6.2"},
    "capabilities": {"tools": {}}
  }
}
```

完整 demo 脚本：[examples/04_mcp_client.py](../../examples/04_mcp_client.py)

## 为什么用 stdio 而非 HTTP？

- ✅ **零网络暴露**（无端口、无认证）
- ✅ IDE 管理进程（启动/重启/沙箱）
- ✅ 标准协议（任何 MCP 客户端都能用）
- ✅ 低延迟（无 HTTP 开销）

## 安全考虑

MCP server 接收任意 JSON-RPC 输入。Pandaone：

- ✅ 严格 JSON 解析（拒绝 malformed）
- ✅ 每个 subprocess 调用有 timeout
- ✅ 错误处理返回标准 JSON-RPC 错误码：
  - `-32700` Parse error
  - `-32601` Method not found
  - `-32602` Invalid params
  - `-32603` Internal error

---

[← 返回首页](index.md) | [查看 CI 集成](ci-integration.md)