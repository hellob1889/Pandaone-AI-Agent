"""
test_mcp_server.py
==================
Phase 6 — Pandaone AI Agent MCP (Model Context Protocol) server。

第一性原理：
  AI Agent 直接通过 shell 调用 CLI 已可用，但 MCP 是标准化协议：
    - JSON-RPC 2.0 over stdio
    - 让 AI 在对话中"发现"和"调用"工具
    - 工具列表、参数 schema 都从服务端动态暴露

设计：
  - pandaone-mcp: 独立 console script（stdio JSON-RPC 2.0）
  - 每个工具 = 一个 CLI 子命令的封装
  - 复用现有 pandaone.py 实现（subprocess 调用），不重写

对抗式审查：
  - 攻击：恶意 stdin 注入
    缓解：JSON-RPC 严格校验，只接受 json 解析成功的请求
  - 攻击：工具调用耗时长阻塞 stdin
    缓解：每个 handler 有 timeout，subprocess 同步
  - 攻击：MCP 进程成为攻击面
    缓解：MCP 不监听端口（stdio），零网络暴露
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"


def _start_mcp_server(extra_env=None):
    """启动 MCP server 子进程（stdio 模式）
    返回 (process, stdout_line_iter) - 用于 send/recv JSON-RPC 消息
    """
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    if extra_env:
        env.update(extra_env)
    # 启动 pandaone_mcp/__main__.py 作为子进程
    p = subprocess.Popen(
        [sys.executable, "-m", "pandaone_mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
        bufsize=1,
    )
    return p


def _send(p: subprocess.Popen, payload: dict) -> dict:
    """发送一条 JSON-RPC 请求并读取响应（一行 JSON）"""
    line = json.dumps(payload, ensure_ascii=False)
    p.stdin.write(line + "\n")
    p.stdin.flush()
    response_line = p.stdout.readline()
    if not response_line:
        err = p.stderr.read() if p.stderr else ""
        raise RuntimeError(f"MCP server 无响应。stderr: {err}")
    return json.loads(response_line)


def _stop(p: subprocess.Popen):
    try:
        if p.poll() is None:
            p.terminate()
            p.wait(timeout=3)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass


# ============================================================
# Step 39: RED 测试
# ============================================================

class TestMCPInitialize:
    """MCP initialize 方法"""

    def test_initialize_returns_protocol_version(self):
        """initialize 应返回协议版本和能力"""
        p = _start_mcp_server()
        try:
            resp = _send(p, {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0.0.1"},
                },
            })
            assert resp["jsonrpc"] == "2.0"
            assert resp["id"] == 1
            assert "result" in resp
            assert "protocolVersion" in resp["result"]
            assert "serverInfo" in resp["result"]
            assert resp["result"]["serverInfo"]["name"] == "pandaone"
        finally:
            _stop(p)


class TestMCPToolsList:
    """MCP tools/list 方法"""

    def test_tools_list_returns_all_tools(self):
        """tools/list 应列出 init/lock/unlock/write/log/status/watch/install-hook/install-git"""
        p = _start_mcp_server()
        try:
            # 先 initialize（部分实现可能要求）
            _send(p, {
                "jsonrpc": "2.0", "id": 0, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                           "clientInfo": {"name": "t", "version": "0"}},
            })
            resp = _send(p, {
                "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}
            })
            assert "result" in resp
            tools = resp["result"]["tools"]
            tool_names = {t["name"] for t in tools}
            # 必须包含的核心工具
            for required in ["pandaone_init", "pandaone_write", "pandaone_log",
                             "pandaone_status", "pandaone_lock", "pandaone_unlock"]:
                assert required in tool_names, f"缺少工具: {required}"
        finally:
            _stop(p)

    def test_each_tool_has_input_schema(self):
        """每个工具应有 inputSchema 描述参数"""
        p = _start_mcp_server()
        try:
            _send(p, {
                "jsonrpc": "2.0", "id": 0, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                           "clientInfo": {"name": "t", "version": "0"}},
            })
            resp = _send(p, {
                "jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}
            })
            tools = resp["result"]["tools"]
            for tool in tools:
                assert "description" in tool, f"工具 {tool.get('name')} 缺 description"
                assert "inputSchema" in tool, f"工具 {tool.get('name')} 缺 inputSchema"
        finally:
            _stop(p)

    def test_each_tool_has_annotations(self):
        """每个工具应有 4 个 annotations（readOnlyHint/destructiveHint/idempotentHint/openWorldHint）

        依据：MCP spec / OpenAI 目录要求 — 4 个 hint 必须全部声明，且为 bool。
        缺一个 → OpenAI 目录拒绝收录。
        """
        p = _start_mcp_server()
        try:
            _send(p, {
                "jsonrpc": "2.0", "id": 0, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                           "clientInfo": {"name": "t", "version": "0"}},
            })
            resp = _send(p, {
                "jsonrpc": "2.0", "id": 31, "method": "tools/list", "params": {}
            })
            tools = resp["result"]["tools"]
            required_hints = ("readOnlyHint", "destructiveHint",
                               "idempotentHint", "openWorldHint")
            assert len(tools) == 11, f"应恰好 11 个工具，实际 {len(tools)}"
            for tool in tools:
                name = tool.get("name", "<unnamed>")
                assert "annotations" in tool, (
                    f"{name} 缺 annotations 块（M8ven trust index 会扣分）"
                )
                ann = tool["annotations"]
                for hint in required_hints:
                    assert hint in ann, f"{name} 缺 {hint}（OpenAI 目录要求）"
                    assert isinstance(ann[hint], bool), (
                        f"{name}.{hint} 必须为 bool，实际 {type(ann[hint]).__name__}={ann[hint]!r}"
                    )
        finally:
            _stop(p)


class TestMCPToolsCall:
    """MCP tools/call 方法"""

    def test_call_init_creates_pandaone_dir(self, tmp_path):
        """调用 pandaone_init 应在目标目录创建 .pandaone/"""
        p = _start_mcp_server()
        try:
            _send(p, {
                "jsonrpc": "2.0", "id": 0, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                           "clientInfo": {"name": "t", "version": "0"}},
            })
            resp = _send(p, {
                "jsonrpc": "2.0", "id": 4, "method": "tools/call",
                "params": {
                    "name": "pandaone_init",
                    "arguments": {"root": str(tmp_path)},
                },
            })
            assert "result" in resp, f"失败: {resp}"
            assert (tmp_path / ".pandaone").exists()
        finally:
            _stop(p)

    def test_call_write_returns_approval(self, tmp_path):
        """调用 pandaone_write 应返回 APPROVED 结果"""
        # 先 init + git init + 初始 commit
        (tmp_path / "main.py").write_text("INITIAL = 1\n", encoding="utf-8")
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC_DIR)
        subprocess.run([sys.executable, "-m", "pandaone", "init", "--root", str(tmp_path)],
                       cwd=str(tmp_path), env=env, capture_output=True)
        # git init
        git = r"D:\软件\Git\cmd\git.exe"
        for cmd in [["init"], ["config", "user.email", "t@t"],
                    ["config", "user.name", "t"], ["add", "-A"]]:
            subprocess.run([git] + cmd, cwd=str(tmp_path), env=env, capture_output=True)
        subprocess.run([git, "commit", "-m", "init"],
                       cwd=str(tmp_path), env=env, capture_output=True)

        p = _start_mcp_server()
        try:
            _send(p, {
                "jsonrpc": "2.0", "id": 0, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                           "clientInfo": {"name": "t", "version": "0"}},
            })
            resp = _send(p, {
                "jsonrpc": "2.0", "id": 5, "method": "tools/call",
                "params": {
                    "name": "pandaone_write",
                    "arguments": {
                        "root": str(tmp_path),
                        "file": "main.py",
                        "reason": "测试 MCP write 调用",
                        "problem": "验证 MCP 服务器能正确调用 CLI",
                        "approach": "通过 MCP 调用 write 子命令",
                        "old": "INITIAL = 1",
                        "new": "INITIAL = 2",
                    },
                },
            })
            assert "result" in resp, f"失败: {resp}"
            content = resp["result"]["content"]
            # 应包含 APPROVED 字样
            assert any("APPROVED" in (c.get("text", "") if isinstance(c, dict) else c)
                       for c in content) if isinstance(content, list) else "APPROVED" in str(content)
        finally:
            _stop(p)

    def test_call_status_returns_dashboard(self, tmp_path):
        """调用 pandaone_status 应返回状态仪表盘信息"""
        # init
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC_DIR)
        subprocess.run([sys.executable, "-m", "pandaone", "init", "--root", str(tmp_path)],
                       cwd=str(tmp_path), env=env, capture_output=True)

        p = _start_mcp_server()
        try:
            _send(p, {
                "jsonrpc": "2.0", "id": 0, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                           "clientInfo": {"name": "t", "version": "0"}},
            })
            resp = _send(p, {
                "jsonrpc": "2.0", "id": 6, "method": "tools/call",
                "params": {
                    "name": "pandaone_status",
                    "arguments": {"root": str(tmp_path)},
                },
            })
            assert "result" in resp
        finally:
            _stop(p)

    def test_call_install_hook_creates_precommit(self, tmp_path):
        """调用 pandaone_install_hook 应在 .git/hooks/pre-commit 写入 hook 脚本"""
        # 先 git init（hook 安装需要 .git/）
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC_DIR)
        subprocess.run([sys.executable, "-m", "pandaone", "init", "--root", str(tmp_path)],
                       cwd=str(tmp_path), env=env, capture_output=True)
        subprocess.run(["git", "init", "-q"], cwd=str(tmp_path),
                       env=env, capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"],
                       env=env, capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"],
                       env=env, capture_output=True)

        p = _start_mcp_server()
        try:
            _send(p, {
                "jsonrpc": "2.0", "id": 0, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                           "clientInfo": {"name": "t", "version": "0"}},
            })
            resp = _send(p, {
                "jsonrpc": "2.0", "id": 7, "method": "tools/call",
                "params": {
                    "name": "pandaone_install_hook",
                    "arguments": {"root": str(tmp_path)},
                },
            })
            assert "result" in resp, f"失败: {resp}"
            hook_file = tmp_path / ".git" / "hooks" / "pre-commit"
            assert hook_file.exists(), f"pre-commit hook 未创建：{hook_file}"
            # hook 内容应含 pandaone 引用
            content = hook_file.read_text(encoding="utf-8", errors="replace")
            assert "pandaone" in content.lower() or "audit" in content.lower(), (
                f"hook 内容异常：{content[:200]}"
            )
        finally:
            _stop(p)

    def test_call_install_git_probe_only_safe(self):
        """调用 pandaone_install_git（默认 probe_only=True）不应触发下载"""
        p = _start_mcp_server()
        try:
            _send(p, {
                "jsonrpc": "2.0", "id": 0, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                           "clientInfo": {"name": "t", "version": "0"}},
            })
            resp = _send(p, {
                "jsonrpc": "2.0", "id": 8, "method": "tools/call",
                "params": {
                    "name": "pandaone_install_git",
                    "arguments": {},
                },
            })
            assert "result" in resp, f"失败: {resp}"
            # 不论 git 是否已装，probe 都不会下载。content 应有 stdout/stderr。
            content = resp["result"].get("content") or []
            assert isinstance(content, list)
        finally:
            _stop(p)

    def test_call_fingerprint_update_writes_hash(self, tmp_path):
        """调用 pandaone_fingerprint_update 应写入密码指纹到 .pandaone/

        前提：CLI 默认密码是 '0000'（get_fingerprint_password()）。
        必须传与默认匹配的密码，否则 CLI 返回 '密码错误，指纹未更新'。
        """
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC_DIR)
        subprocess.run([sys.executable, "-m", "pandaone", "init", "--root", str(tmp_path)],
                       cwd=str(tmp_path), env=env, capture_output=True)

        p = _start_mcp_server()
        try:
            _send(p, {
                "jsonrpc": "2.0", "id": 0, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                           "clientInfo": {"name": "t", "version": "0"}},
            })
            # 传默认密码 "0000"（pandaone/cli_chunks/part_002.py:_DEFAULT_FP_PASSWORD）
            resp = _send(p, {
                "jsonrpc": "2.0", "id": 9, "method": "tools/call",
                "params": {
                    "name": "pandaone_fingerprint_update",
                    "arguments": {"password": "0000"},
                },
            })
            assert "result" in resp, f"失败: {resp}"
            # 返回不应是 error
            assert resp["result"].get("isError") is not True, (
                f"指纹更新失败：{resp['result']}"
            )
        finally:
            _stop(p)

    def test_call_ci_reachable_returns_verification(self, tmp_path):
        """调用 pandaone_ci 应可达（即使 base 分支不存在也返回结构化响应，不崩溃）"""
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC_DIR)
        # init + git init + 初始 commit（让 ci 至少有 base 可比）
        subprocess.run([sys.executable, "-m", "pandaone", "init", "--root", str(tmp_path)],
                       cwd=str(tmp_path), env=env, capture_output=True)
        subprocess.run(["git", "init", "-q"], cwd=str(tmp_path),
                       env=env, capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"],
                       env=env, capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"],
                       env=env, capture_output=True)
        # 制造一个 dummy 文件让 init 完成
        (tmp_path / "README.md").write_text("# test\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(tmp_path), "add", "-A"],
                       env=env, capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "initial"],
                       env=env, capture_output=True)

        p = _start_mcp_server()
        try:
            _send(p, {
                "jsonrpc": "2.0", "id": 0, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                           "clientInfo": {"name": "t", "version": "0"}},
            })
            # 用 HEAD 自身作 base（避免 origin/main 不存在的副作用）
            resp = _send(p, {
                "jsonrpc": "2.0", "id": 10, "method": "tools/call",
                "params": {
                    "name": "pandaone_ci",
                    "arguments": {
                        "root": str(tmp_path),
                        "base": "HEAD",
                        "head": "HEAD",
                    },
                },
            })
            assert "result" in resp or "error" in resp, (
                f"MCP 服务器应返回结构化响应（result 或 error），实际：{resp}"
            )
            # 不论 result 还是 error，都不应是协议级崩溃
            assert "jsonrpc" in resp
        finally:
            _stop(p)


class TestMCPErrors:
    """错误处理"""

    def test_unknown_tool_returns_error(self):
        """调用未知工具应返回 error 而不是崩溃"""
        p = _start_mcp_server()
        try:
            _send(p, {
                "jsonrpc": "2.0", "id": 0, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                           "clientInfo": {"name": "t", "version": "0"}},
            })
            resp = _send(p, {
                "jsonrpc": "2.0", "id": 7, "method": "tools/call",
                "params": {"name": "nonexistent_tool", "arguments": {}},
            })
            assert "error" in resp or resp.get("result", {}).get("isError") is True
        finally:
            _stop(p)

    def test_invalid_json_returns_parse_error(self):
        """非法 JSON 应返回 parse error，不崩溃"""
        p = _start_mcp_server()
        try:
            p.stdin.write("this is not json\n")
            p.stdin.flush()
            resp_line = p.stdout.readline()
            resp = json.loads(resp_line)
            assert "error" in resp
            assert resp["error"]["code"] == -32700  # JSON-RPC parse error
        finally:
            _stop(p)


class TestMCPCLIIntegration:
    """pandaone-mcp 命令行入口"""

    def test_mcp_console_script_exists(self):
        """pyproject.toml 应注册 pandaone-mcp console script"""
        import re
        pyproject = (ROOT_DIR / "pyproject.toml").read_text(encoding="utf-8")
        assert "pandaone-mcp" in pyproject, "pyproject.toml 应包含 pandaone-mcp console script"

    def test_mcp_module_importable(self):
        """pandaone_mcp 包应可导入"""
        sys.path.insert(0, str(SRC_DIR))
        try:
            import pandaone_mcp
            assert pandaone_mcp is not None
        finally:
            # cleanup sys.path
            if str(SRC_DIR) in sys.path:
                sys.path.remove(str(SRC_DIR))