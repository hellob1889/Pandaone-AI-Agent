"""
test_watchdog_dedupe.py
=======================
Bug #23 + #24 RED 测试：watchdog dedupe + stdout flush。

第一性原理：
  watchdog 监听文件系统事件，但 PowerShell Out-File / 一些编辑器
  对单次写入会触发多次 on_modified。
  之前代码：每次 on_modified 都写 UNAUTHORIZED → 1 次实际改动产生 4 条记录（噪音污染）。
  修复：维护 (path, event_type) → last_fire_time 字典，2 秒窗口内视为重复并跳过。

  #24：前台 pandaone watch 的 print() 没 flush，输出被 Python 缓冲，
       用户看到 watch 启动后无任何输出（怀疑没运行）。修复：print(..., flush=True)。
"""
import io
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "src"


# ============================================================
# Bug #23: watchdog dedupe
# ============================================================

class TestWatchdogDedupe:
    """Bug #23 — on_modified 单次写入应只产生 1 条 UNAUTHORIZED 记录"""

    def _setup_project(self, tmp_path):
        """建项目 + 锁定 main.py"""
        from pandaone_guard import PandaXHandler
        # 初始化项目（直接写 .pandaone 目录避免依赖 pandaone init CLI）
        pandaone_dir = tmp_path / ".pandaone"
        pandaone_dir.mkdir()
        config = {
            "protected_extensions": [".py"],
            "binary_protected_extensions": [],
        }
        (pandaone_dir / "config.json").write_text(
            json.dumps(config, ensure_ascii=False), encoding="utf-8",
        )
        # 确保没有 audit token
        assert not (pandaone_dir / ".audit_token").exists()
        return PandaXHandler(tmp_path)

    def _make_modified_event(self, path: Path):
        """构造一个 watchdog FileModifiedEvent"""
        from watchdog.events import FileModifiedEvent
        return FileModifiedEvent(str(path))

    def test_on_modified_dedupes_repeats_within_window(self, tmp_path):
        """同一文件 2 秒内多次 on_modified 只产生 1 条审计记录"""
        handler = self._setup_project(tmp_path)
        main_py = tmp_path / "main.py"
        main_py.write_text("x = 1\n", encoding="utf-8")

        ev = self._make_modified_event(main_py)

        # 模拟 PowerShell Out-File 等编辑器：1 次写入触发 5 次 on_modified
        for _ in range(5):
            handler.on_modified(ev)

        # Bug #23 验证：应只有 1 条 UNAUTHORIZED 记录（不是 5 条）
        records = [
            json.loads(line)
            for line in (tmp_path / ".pandaone" / "pandaone.jsonl").read_text(
                encoding="utf-8",
            ).splitlines()
            if line.strip()
        ]
        assert len(records) == 1, (
            f"Bug #23 回归：5 次 on_modified 产生 {len(records)} 条审计记录（应为 1）: {records}"
        )
        assert records[0]["status"] == "UNAUTHORIZED"

    def test_on_modified_after_window_creates_new_record(self, tmp_path):
        """超出 2 秒窗口的修改应产生新记录"""
        handler = self._setup_project(tmp_path)
        main_py = tmp_path / "main.py"
        main_py.write_text("x = 1\n", encoding="utf-8")
        ev = self._make_modified_event(main_py)

        # 第一次事件
        handler.on_modified(ev)
        # 伪造时间流逝（直接改 _recent_events 时间戳）
        key = ("main.py", "modified")
        handler._recent_events[key] = time.time() - 3.0  # 3 秒前

        # 第二次事件（视为新事件）
        handler.on_modified(ev)

        records = [
            json.loads(line)
            for line in (tmp_path / ".pandaone" / "pandaone.jsonl").read_text(
                encoding="utf-8",
            ).splitlines()
            if line.strip()
        ]
        assert len(records) == 2, (
            f"Bug #23 回归：超窗口后第 2 次事件未产生新记录: {records}"
        )

    def test_on_moved_dedupes_independently_from_modified(self, tmp_path):
        """on_moved 与 on_modified 是独立事件类型（key 含 event_type）"""
        from watchdog.events import FileMovedEvent
        handler = self._setup_project(tmp_path)
        main_py = tmp_path / "main.py"
        main_py.write_text("x = 1\n", encoding="utf-8")

        # 一次 modified
        handler.on_modified(self._make_modified_event(main_py))
        # 一次 moved（不同事件类型，不应被 modified 的去重影响）
        handler.on_moved(FileMovedEvent(str(main_py), str(main_py)))

        records = [
            json.loads(line)
            for line in (tmp_path / ".pandaone" / "pandaone.jsonl").read_text(
                encoding="utf-8",
            ).splitlines()
            if line.strip()
        ]
        # 应有 2 条记录（modified + moved）
        assert len(records) == 2, (
            f"Bug #23 回归：modified 与 moved 事件类型应独立去重: {records}"
        )

    def test_dedupe_state_clears_stale_entries(self, tmp_path):
        """防止 _recent_events 字典无限增长（10×窗口后清理）"""
        handler = self._setup_project(tmp_path)
        # 注入 100 个超期条目
        old = time.time() - 100.0
        for i in range(100):
            handler._recent_events[(f"file_{i}.py", "modified")] = old

        # 触发一次新事件，触发清理
        main_py = tmp_path / "main.py"
        main_py.write_text("x = 1\n", encoding="utf-8")
        handler.on_modified(self._make_modified_event(main_py))

        # 旧条目应被清理（只剩当前 1 条）
        assert len(handler._recent_events) <= 2, (
            f"_recent_events 未清理：剩 {len(handler._recent_events)} 条"
        )


# ============================================================
# Bug #24: stdout flush
# ============================================================

class TestWatchdogStdoutFlush:
    """Bug #24 — watchdog 进程 print 必须显式 flush（不被 Python 缓冲）"""

    def test_all_prints_in_pandaone_guard_use_flush(self):
        """对抗式审查：所有 print() 必须显式 flush=True"""
        # 静态扫描 src/pandaone_guard/__main__.py
        guard_path = SRC_DIR / "pandaone_guard" / "__main__.py"
        source = guard_path.read_text(encoding="utf-8")

        # 找出所有 print( 调用（用 AST 解析跨行场景更稳）
        import ast
        tree = ast.parse(source)
        bad_prints = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # 检查被调函数名是否为 print
                func = node.func
                if isinstance(func, ast.Name) and func.id == "print":
                    # 检查是否有 flush=True 关键字参数
                    has_flush = any(
                        kw.arg == "flush" and kw.value.value is True
                        for kw in node.keywords
                    )
                    if not has_flush:
                        # 取源码片段（最多 80 字符）
                        snippet = ast.get_source_segment(source, node) or "<unknown>"
                        bad_prints.append(snippet[:120])
        assert not bad_prints, (
            f"Bug #24 回归：以下 print() 缺 flush=True:\n"
            + "\n".join(f"  {p}" for p in bad_prints)
        )

    def test_pandaone_watch_daemon_sets_pythonunbuffered(self):
        """cli cmd_watch --daemon 子进程必须设 PYTHONUNBUFFERED=1

        v0.7.15 fix: cli.py 自 v0.7.7 起是 chunk loader，实际代码在
        cli_chunks/part_005.py。静态检查必须读 chunks 而不是 loader。
        """
        chunk_files = sorted((SRC_DIR / "pandaone" / "cli_chunks").glob("part_*.py"))
        source = "\n".join(p.read_text(encoding="utf-8") for p in chunk_files)

        # 在 daemon 模式 subprocess.Popen 调用附近必须有 PYTHONUNBUFFERED
        # 检查 pattern: env={**os.environ, "PYTHONUNBUFFERED": "1"}
        assert "PYTHONUNBUFFERED" in source, (
            "Bug #24 回归：cli.py cmd_watch --daemon 未设 PYTHONUNBUFFERED"
        )
        # 找到 daemon Popen 处的 env 设置
        m = re.search(
            r"subprocess\.Popen\([^)]*?env=\{[^}]*PYTHONUNBUFFERED[^}]*\}",
            source,
            re.DOTALL,
        )
        assert m, (
            "Bug #24 回归：Popen env dict 中找不到 PYTHONUNBUFFERED"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
