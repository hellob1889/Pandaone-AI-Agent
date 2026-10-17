"""测试 pandaone_serve.py:watchdog 监视 + SSE 事件总线 + HTTP server。

第一性原则:
  - SSE 推送必须 <100ms(watchdog → SSE)
  - 多客户端订阅互不干扰
  - 优雅处理断连
  - 端口冲突自动探测
"""
import json
import queue
import socket
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pandaone import pandaone_serve as _ps_mod  # v0.7.19 hotfix 2: patch.object target
from pandaone.pandaone_serve import (
    AuditEventBus, AuditFileMonitor, _find_free_port, HAS_WATCHDOG,
)


# ============================================================
# AuditEventBus 单元测试
# ============================================================

class TestAuditEventBus:
    def test_subscribe_returns_queue(self):
        bus = AuditEventBus()
        q = bus.subscribe()
        assert isinstance(q, queue.Queue)

    def test_publish_delivers_to_subscriber(self):
        bus = AuditEventBus()
        q = bus.subscribe()
        bus.publish({"type": "test", "data": 1})
        evt = q.get(timeout=2)
        assert evt == {"type": "test", "data": 1}

    def test_multiple_subscribers(self):
        bus = AuditEventBus()
        q1 = bus.subscribe()
        q2 = bus.subscribe()
        bus.publish({"type": "x", "data": 42})
        assert q1.get(timeout=2)["data"] == 42
        assert q2.get(timeout=2)["data"] == 42

    def test_unsubscribe_removes(self):
        bus = AuditEventBus()
        q = bus.subscribe()
        assert bus.subscriber_count == 1
        bus.unsubscribe(q)
        assert bus.subscriber_count == 0

    def test_publish_doesnt_block_when_subscriber_slow(self):
        """慢订阅者不应阻塞 publish。"""
        bus = AuditEventBus()
        # 容量极小的 queue
        q = bus.subscribe(maxsize=2)
        # 发布 100 条,不应卡死
        for i in range(100):
            bus.publish({"type": "test", "data": i})
        # 不抛异常即可

    def test_publish_to_no_subscribers(self):
        bus = AuditEventBus()
        # 无订阅者时 publish 应正常返回
        bus.publish({"type": "x"})  # 不抛异常


# ============================================================
# _find_free_port 单元测试
# ============================================================

class TestFindFreePort:
    def test_returns_int(self):
        port = _find_free_port(19000, max_tries=5)
        assert isinstance(port, int)
        assert 19000 <= port < 19005

    def test_finds_unused_port(self):
        # 占用一个端口,验证 _find_free_port 跳过它
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 19100))
            s.listen(1)
            port = _find_free_port(19100, max_tries=10)
            assert port != 19100
            assert port >= 19101


# ============================================================
# AuditFileMonitor 单元测试
# ============================================================

class TestAuditFileMonitor:
    def test_start_returns_false_when_no_audit_file(self, tmp_path):
        bus = AuditEventBus()
        monitor = AuditFileMonitor(tmp_path, bus)
        assert monitor.start() is False  # 没 .pandaone/pandaone.jsonl

    @pytest.mark.skipif(not HAS_WATCHDOG, reason="watchdog 未安装")
    def test_start_returns_false_when_watchdog_missing(self, tmp_path):
        # 模拟 watchdog 缺失
        (tmp_path / ".pandaone").mkdir()
        (tmp_path / ".pandaone" / "pandaone.jsonl").touch()
        bus = AuditEventBus()
        monitor = AuditFileMonitor(tmp_path, bus)
        with patch.object(_ps_mod, "HAS_WATCHDOG", False):
            assert monitor.start() is False

    @pytest.mark.skipif(not HAS_WATCHDOG, reason="watchdog 未安装")
    def test_monitor_publishes_history_on_start(self, tmp_path):
        """启动 monitor 时,历史记录应全部 publish。"""
        (tmp_path / ".pandaone").mkdir()
        # 写 3 条历史
        records = [
            {"status": "APPROVED", "id": f"h{i}", "file": "main.py",
             "reason": f"hist {i}", "timestamp": "2026-09-06 10:00:00"}
            for i in range(3)
        ]
        with open(tmp_path / ".pandaone" / "pandaone.jsonl", "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        bus = AuditEventBus()
        q = bus.subscribe()
        monitor = AuditFileMonitor(tmp_path, bus)
        assert monitor.start() is True
        try:
            # 等待 history 推送
            time.sleep(0.3)
            received = []
            while not q.empty():
                received.append(q.get_nowait())
            # 至少 3 条 audit_history 事件
            history = [e for e in received if e.get("type") == "audit_history"]
            assert len(history) == 3
            assert history[0]["data"]["id"] == "h0"
            assert history[2]["data"]["id"] == "h2"
        finally:
            monitor.stop()

    @pytest.mark.skipif(not HAS_WATCHDOG, reason="watchdog 未安装")
    def test_monitor_publishes_new_writes(self, tmp_path):
        """启动后追加新行,应通过 watchdog 推送到 bus。"""
        (tmp_path / ".pandaone").mkdir()
        audit = tmp_path / ".pandaone" / "pandaone.jsonl"
        audit.touch()

        bus = AuditEventBus()
        q = bus.subscribe()
        monitor = AuditFileMonitor(tmp_path, bus)
        assert monitor.start() is True
        try:
            time.sleep(0.2)  # 等 observer 就绪
            # 追加新事件
            new_record = {"status": "REJECTED", "id": "fresh_001",
                          "file": "x.py", "reason": "fresh write test",
                          "timestamp": "2026-09-06 11:00:00"}
            with open(audit, "a", encoding="utf-8") as f:
                f.write(json.dumps(new_record) + "\n")
                f.flush()
            # 等 watchdog 触发
            time.sleep(0.5)
            # 找新事件
            found = []
            while not q.empty():
                found.append(q.get_nowait())
            # 至少一条 audit 事件
            audit_events = [e for e in found if e.get("type") == "audit"]
            assert len(audit_events) >= 1
            ids = [e["data"]["id"] for e in audit_events]
            assert "fresh_001" in ids
        finally:
            monitor.stop()


# ============================================================
# HTTP server 端到端测试
# ============================================================

class TestServeHTTP:
    """端到端:启动 server + GET / + GET /api/ping + GET /api/stats。"""

    def test_get_index_html(self, tmp_path):
        import urllib.request
        from pandaone.pandaone_serve import start_server
        (tmp_path / ".pandaone").mkdir()
        (tmp_path / ".pandaone" / "config.json").write_text("{}")
        (tmp_path / ".pandaone" / "pandaone.jsonl").touch()

        server, monitor = start_server(tmp_path, port=19200, open_browser=False)
        try:
            with urllib.request.urlopen("http://127.0.0.1:19200/", timeout=5) as r:
                html = r.read().decode("utf-8")
                assert r.status == 200
                assert "Pandaone AI Agent" in html
                assert "EventSource" in html
        finally:
            monitor.stop()
            server.shutdown()
            server.server_close()

    def test_api_ping(self, tmp_path):
        import urllib.request
        from pandaone.pandaone_serve import start_server
        (tmp_path / ".pandaone").mkdir()
        (tmp_path / ".pandaone" / "config.json").write_text("{}")
        (tmp_path / ".pandaone" / "pandaone.jsonl").touch()

        server, monitor = start_server(tmp_path, port=19201, open_browser=False)
        try:
            with urllib.request.urlopen("http://127.0.0.1:19201/api/ping", timeout=5) as r:
                body = json.loads(r.read())
                assert body["pong"] is True
        finally:
            monitor.stop()
            server.shutdown()
            server.server_close()

    def test_api_stats_with_real_audit(self, tmp_path):
        import urllib.request
        from pandaone.pandaone_serve import start_server
        (tmp_path / ".pandaone").mkdir()
        (tmp_path / ".pandaone" / "config.json").write_text("{}")
        audit = tmp_path / ".pandaone" / "pandaone.jsonl"
        # 写一些混合状态的审计
        records = [
            {"status": "APPROVED", "id": "1"},
            {"status": "APPROVED", "id": "2"},
            {"status": "REJECTED", "id": "3"},
            {"status": "UNAUTHORIZED", "id": "4"},
        ]
        with open(audit, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        server, monitor = start_server(tmp_path, port=19202, open_browser=False)
        try:
            with urllib.request.urlopen("http://127.0.0.1:19202/api/stats", timeout=5) as r:
                body = json.loads(r.read())
                assert body["total"] == 4
                assert body["APPROVED"] == 2
                assert body["REJECTED"] == 1
                assert body["UNAUTHORIZED"] == 1
        finally:
            monitor.stop()
            server.shutdown()
            server.server_close()


# ============================================================
# SSE 端到端测试
# ============================================================

class TestServeSSE:
    """端到端:SSE 实时推送。"""

    def test_sse_sends_connected_event(self, tmp_path):
        import urllib.request
        from pandaone.pandaone_serve import start_server
        (tmp_path / ".pandaone").mkdir()
        (tmp_path / ".pandaone" / "config.json").write_text("{}")
        (tmp_path / ".pandaone" / "pandaone.jsonl").touch()

        server, monitor = start_server(tmp_path, port=19203, open_browser=False)

        events_received = []
        done = threading.Event()

        def listener():
            try:
                req = urllib.request.Request(
                    "http://127.0.0.1:19203/api/events",
                    headers={"Accept": "text/event-stream"},
                )
                with urllib.request.urlopen(req, timeout=3) as r:
                    buf = b""
                    deadline = time.time() + 2
                    while time.time() < deadline and not done.is_set():
                        try:
                            chunk = r.read(1)
                        except Exception:
                            break
                        if not chunk:
                            break
                        buf += chunk
                        if buf.endswith(b"\n\n"):
                            text = buf.decode("utf-8").strip()
                            if text and not text.startswith(":"):
                                events_received.append(text)
                                if "connected" in text:
                                    done.set()
                                    return
                            buf = b""
            except Exception:
                pass

        t = threading.Thread(target=listener, daemon=True)
        t.start()
        t.join(timeout=3)

        try:
            assert done.is_set(), f"未在 2s 内收到 connected 事件: {events_received}"
            assert any("connected" in e for e in events_received)
        finally:
            done.set()
            monitor.stop()
            server.shutdown()
            server.server_close()

    @pytest.mark.skipif(not HAS_WATCHDOG, reason="watchdog 未安装")
    def test_sse_pushes_new_audit_realtime(self, tmp_path):
        """端到端:写新审计 → SSE 立即推送 → 客户端收到。"""
        import urllib.request
        from pandaone.pandaone_serve import start_server
        (tmp_path / ".pandaone").mkdir()
        (tmp_path / ".pandaone" / "config.json").write_text("{}")
        audit = tmp_path / ".pandaone" / "pandaone.jsonl"
        audit.touch()

        server, monitor = start_server(tmp_path, port=19204, open_browser=False)
        events_received = []
        done = threading.Event()

        def listener():
            try:
                req = urllib.request.Request(
                    "http://127.0.0.1:19204/api/events",
                    headers={"Accept": "text/event-stream"},
                )
                with urllib.request.urlopen(req, timeout=5) as r:
                    buf = b""
                    deadline = time.time() + 5
                    while time.time() < deadline and not done.is_set():
                        try:
                            chunk = r.read(1)
                        except Exception:
                            break
                        if not chunk:
                            break
                        buf += chunk
                        if buf.endswith(b"\n\n"):
                            text = buf.decode("utf-8").strip()
                            if text and "audit_e2e_001" in text:
                                events_received.append(text)
                                done.set()
                                return
                            buf = b""
            except Exception:
                pass

        t = threading.Thread(target=listener, daemon=True)
        t.start()
        time.sleep(0.5)  # 等 connected + observer 就绪

        # 追加新审计
        new_event = {"status": "APPROVED", "id": "audit_e2e_001",
                     "file": "test.py", "reason": "SSE push test",
                     "timestamp": "2026-09-06 12:00:00"}
        with open(audit, "a", encoding="utf-8") as f:
            f.write(json.dumps(new_event) + "\n")
            f.flush()

        t.join(timeout=4)
        try:
            assert done.is_set(), f"未在 4s 内收到 audit_e2e_001: {events_received}"
        finally:
            done.set()
            monitor.stop()
            server.shutdown()
            server.server_close()


# ============================================================
# cmd_serve 集成测试
# ============================================================

class TestCmdServe:
    def test_cmd_serve_rejects_non_init_directory(self, tmp_path):
        """未 init 目录应被拒绝(类似 cmd_lock)。"""
        from pandaone.cli import cmd_serve
        import argparse
        args = argparse.Namespace(root=str(tmp_path), port=8765)
        # cmd_serve 用 from import 引用 run_blocking,patch 源模块
        with patch("pandaone.pandaone_serve.run_blocking") as mock_run:
            mock_run.return_value = 0
            rc = cmd_serve(args)
        assert rc == 1  # 未 init 应返回 1
        mock_run.assert_not_called()  # 不应真启动

    def test_cmd_serve_runs_blocking_for_init_dir(self, tmp_path):
        """已 init 目录应调用 run_blocking。"""
        from pandaone.cli import cmd_serve
        (tmp_path / ".pandaone").mkdir()
        (tmp_path / ".pandaone" / "config.json").write_text("{}")
        import argparse
        args = argparse.Namespace(root=str(tmp_path), port=8765)
        with patch("pandaone.pandaone_serve.run_blocking") as mock_run:
            mock_run.return_value = 0
            rc = cmd_serve(args)
        assert rc == 0
        mock_run.assert_called_once()
        # 验证参数
        call_args = mock_run.call_args
        assert call_args.kwargs["port"] == 8765


# ============================================================
# index.html 合规性测试
# ============================================================

class TestIndexHtml:
    """确保 index.html 包含所有必要元素。"""

    def test_index_html_contains_key_elements(self):
        from importlib import resources
        try:
            html = resources.files("pandaone").joinpath("index.html").read_text("utf-8")
        except Exception:
            # fallback
            html = (Path(__file__).parent.parent / "src" / "pandaone" / "index.html").read_text("utf-8")

        # 必要元素
        assert "Pandaone" in html
        assert "EventSource" in html  # SSE 客户端
        assert "🐼" in html  # 熊猫品牌
        assert "APPROVED" in html
        assert "REJECTED" in html
        assert "UNAUTHORIZED" in html
        # 现代明亮主题
        assert "--bg: #fafaf9" in html or "#fafaf9" in html
        assert "backdrop-filter" in html  # 现代玻璃效果
        # 实时统计
        assert "statTotal" in html
        # 搜索过滤
        assert "searchInput" in html


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])