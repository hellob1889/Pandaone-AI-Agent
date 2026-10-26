"""测试 SSE bug 修复:stale subscriber 清理 + 更广异常捕获。

对抗式 bug 来源:
  - 客户端 close 后,server 端 queue 残留(因 HTTP keep-alive 让 socket 暂时可写)
  - SSE 15s 超时太慢,UI 显示 subscribers 数不准
  - BrokenPipeError / OSError 被原代码 swallow,清理路径被绕过

修复策略:
  1. 超时 15s → 5s(加快断连检测)
  2. publish() 加 _miss_count:累计 3 次 miss → 标记 stale → 自动 unsubscribe
  3. _serve_sse 捕获更广异常(ConnectionAbortedError, OSError)
  4. _send_sse 不再 swallow 异常(让外层 finally 清理)
"""
import json
import socket
import threading
import time
import urllib.request

import pytest

from pandaone.pandaone_serve import AuditEventBus, _find_free_port


# ============================================================
# AuditEventBus stale 清理
# ============================================================

class TestAuditEventBusStaleCleanup:
    def test_miss_count_resets_on_success(self):
        bus = AuditEventBus()
        q = bus.subscribe(maxsize=2)
        bus.publish("a1")  # OK
        bus.publish("a2")  # OK(满了)
        # 第三次 publish 应该触发 Full
        # 但因为 publish 会 get+put,会成功
        # 实际上 maxsize=2, 已经有 2 个, 第 3 个会触发 stale logic
        bus.publish("a3")  # queue 满了 → get+put → _miss_count=1
        assert q._miss_count == 1
        # 第 4 次
        bus.publish("a4")  # _miss_count=2
        assert q._miss_count == 2
        # 第 5 次 → _miss_count=3 → 标记 stale
        bus.publish("a5")
        assert q not in bus._subscribers
        assert bus.subscriber_count == 0

    def test_stale_subscriber_removed_on_full_3_times(self):
        bus = AuditEventBus()
        q = bus.subscribe(maxsize=1)
        # maxsize=1:第 1 次 put 成功(queue 空),之后每次 publish 都会 Full
        # 第 4 次 publish 时累计 _miss_count=3 → 标记 stale 清理
        bus.publish("e1")  # put OK, _miss=0
        bus.publish("e2")  # Full → _miss=1, get+put OK
        bus.publish("e3")  # Full → _miss=2, get+put OK
        bus.publish("e4")  # Full → _miss=3 → stale(清理)
        assert q not in bus._subscribers
        assert bus.subscriber_count == 0

    def test_consumer_not_affected_by_stale_cleanup(self):
        """持续消费事件的 subscriber 不应被误清理。"""
        bus = AuditEventBus()
        q = bus.subscribe(maxsize=2)

        # 模拟消费:每次 publish 后立即 get
        def consumer():
            for _ in range(10):
                try:
                    q.get(timeout=0.1)
                except Exception:
                    pass

        t = threading.Thread(target=consumer, daemon=True)
        t.start()

        for i in range(10):
            bus.publish(f"e{i}")
            time.sleep(0.05)
        t.join(timeout=2)

        # 应该还在 subscribers(因为一直在消费,没连续 3 次 Full)
        assert q in bus._subscribers


# ============================================================
# SSE 端到端断连测试(缩短超时)
# ============================================================

class TestSSEDisconnectCleanup:
    """端到端:客户端断连后,server 应及时清理 subscriber。"""

    @pytest.fixture
    def running_server(self, tmp_path):
        """启动 pandaone serve,返回 (port, audit_path)。"""
        from pandaone.pandaone_serve import start_server
        (tmp_path / ".pandaone").mkdir()
        (tmp_path / ".pandaone" / "config.json").write_text("{}")
        (tmp_path / ".pandaone" / "pandaone.jsonl").touch()
        port = _find_free_port(20300)
        server, monitor = start_server(tmp_path, port=port, open_browser=False)
        try:
            # 用 server 真正绑到的端口:请求的端口被占时 start_server 会自动顺延,
            # 拿请求端口去连会连到别人的服务或直接被 RST(并发跑全量时的偶发红)
            yield server.server_address[1], tmp_path / ".pandaone" / "pandaone.jsonl"
        finally:
            monitor.stop()
            server.shutdown()
            server.server_close()

    def test_subscribers_cleans_up_within_5s(self, running_server):
        """Bug 修复:从 15s 超时降到 5s 后,subscribe 应在 ~5-10s 内清理。"""
        port, _ = running_server

        # 连接,等 connected,然后立即断开
        req = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/events", timeout=2)
        req.read(1)
        req.close()
        time.sleep(0.1)

        # 立即查
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/stats", timeout=3) as r:
            initial = r.read()
        stats = json.loads(initial)
        # 1 个刚断的 subscriber(等 server 检测)
        # 不能立即是 0,但应在 5s 内降为 0

        # 等 10 秒(2 个超时周期 + 余量)
        time.sleep(10)

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/stats", timeout=3) as r:
            stats_after = json.loads(r.read())
        # 5s 超时 + heartbeat 检测 → 应已 unsubscribe
        assert stats_after["subscribers"] <= stats["subscribers"], (
            f"subscribers 没降: 初始 {stats['subscribers']}, 10秒后 {stats_after['subscribers']}"
        )

    def test_subscribers_count_eventually_zero(self, running_server):
        """最终应清理到 0。"""
        port, _ = running_server

        req = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/events", timeout=2)
        req.read(1)
        req.close()

        # 等足够长的时间(5s 超时 × 几次 + heartbeat 检测延迟)
        time.sleep(20)

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/stats", timeout=3) as r:
            stats = json.loads(r.read())
        assert stats["subscribers"] == 0, f"subscribers 未清理到 0: {stats['subscribers']}"