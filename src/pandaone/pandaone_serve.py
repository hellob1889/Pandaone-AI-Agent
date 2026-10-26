"""Pandaone AI Agent Web 仪表盘后端(watchdog + HTTP + SSE 三合一)。

第一性原理:
  - 用户想要"实时看到 Agent 修改的内容"
  - 审计日志写入 .pandaone/pandaone.jsonl(append-only)
  - 用 watchdog 监视文件 append → SSE 推送到浏览器
  - 浏览器渲染现代明亮仪表盘

架构:
  Agent write → .pandaone/pandaone.jsonl (append)
                          ↓ watchdog Observer(<50ms)
                  FileChangeHandler
                          ↓ queue.Queue
                  HTTP server (内置 SimpleHTTPRequestHandler + SSE)
                          ↓ EventSource
                  Browser UI

对抗式审查:
  - 端口冲突?支持 --port 自定义 + 自动探测下一个可用端口
  - 多客户端?每个 SSE 连接独立 queue,互不干扰
  - 性能?queue.Queue 异步,handler 不阻塞 file monitor
  - 安全?只绑定 127.0.0.1(不暴露 LAN,防局域网扫描)
  - 优雅退出?捕获 KeyboardInterrupt,关闭所有 handler
"""
from __future__ import annotations

import json
import queue
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False

try:
    from .i18n import t as _t
except ImportError:
    def _t(key, **kwargs):
        # 无 i18n 时回退到 key 本身,避免崩溃
        return key


# ============================================================
# 核心:审计事件队列 + 文件监视器
# ============================================================

class AuditEventBus:
    """多客户端 SSE 事件总线。

    每个连接的客户端有自己的 queue。文件 append 时,事件 fan-out 到所有 queue。
    """

    def __init__(self):
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()

    def subscribe(self, maxsize: int = 1000) -> queue.Queue:
        """新客户端订阅,返回专属 queue。"""
        q: queue.Queue = queue.Queue(maxsize=maxsize)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        """客户端断开时清理。"""
        with self._lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    def publish(self, event: dict[str, Any]) -> None:
        """广播事件到所有订阅者。满了就丢弃最老的,保活。

        Bug 修复(对抗式 SSE 测试发现):
          - 当 queue 多次 Full 时,标记为 stale 并清理
          - 防止 HTTP keep-alive 复用 socket 时 dead subscriber 永久残留
        """
        with self._lock:
            stale = []
            for q in self._subscribers:
                # 第一遍尝试:正常 put
                try:
                    q.put_nowait(event)
                    q._miss_count = 0  # 重置 miss 计数
                except queue.Full:
                    # 队列满:说明 client 消费慢(可能已断开)
                    q._miss_count = getattr(q, "_miss_count", 0) + 1
                    # 累计 3 次 miss → 认为是 stale,清理
                    if q._miss_count >= 3:
                        stale.append(q)
                        continue
                    # 否则丢最老的,放入新事件(给 client 一次机会)
                    try:
                        q.get_nowait()
                        q.put_nowait(event)
                    except Exception:
                        stale.append(q)
            for q in stale:
                try:
                    self._subscribers.remove(q)
                except ValueError:
                    pass

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)


class _AuditFileHandler(FileSystemEventHandler if HAS_WATCHDOG else object):
    """watchdog handler:.pandaone/pandaone.jsonl append 时读取新行并发布事件。"""

    def __init__(self, audit_path: Path, bus: AuditEventBus, start_offset: int = 0):
        self.audit_path = audit_path
        self.bus = bus
        self._offset = start_offset
        self._lock = threading.Lock()

    def _read_new_lines(self) -> list[dict]:
        """从上次 offset 开始读取新行,解析为 dict。"""
        with self._lock:
            if not self.audit_path.exists():
                return []
            try:
                with open(self.audit_path, "rb") as f:
                    f.seek(self._offset)
                    raw = f.read()
                    self._offset = f.tell()
            except OSError:
                return []
        if not raw:
            return []
        events = []
        for line in raw.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return events

    def on_modified(self, event):
        """watchdog 触发文件变化时调用。"""
        if event.is_directory:
            return
        # 只关心 pandaone.jsonl(可能是其他文件变化,过滤掉)
        if Path(event.src_path).resolve() != self.audit_path.resolve():
            return
        for evt in self._read_new_lines():
            self.bus.publish({"type": "audit", "data": evt})


class AuditFileMonitor:
    """启动 watchdog 监视 .pandaone/pandaone.jsonl,启动时回放历史 + 实时增量。"""

    def __init__(self, root: Path, bus: AuditEventBus):
        self.root = Path(root).resolve()
        self.audit_path = self.root / ".pandaone" / "pandaone.jsonl"
        self.bus = bus
        self._observer = None
        self._handler = None

    def start(self) -> bool:
        """启动文件监视。返回 True = 成功,False = 失败(没 watchdog 或无 audit 文件)。"""
        if not HAS_WATCHDOG:
            return False
        if not self.audit_path.exists():
            return False

        # 启动时回放历史(全量)
        try:
            with open(self.audit_path, "rb") as f:
                raw = f.read()
            for line in raw.decode("utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    self.bus.publish({"type": "audit_history", "data": json.loads(line)})
                except json.JSONDecodeError:
                    continue
        except OSError:
            pass

        # 启动 watchdog observer
        self._handler = _AuditFileHandler(self.audit_path, self.bus)
        self._observer = Observer()
        self._observer.schedule(self._handler, str(self.audit_path.parent), recursive=False)
        self._observer.daemon = True
        self._observer.start()
        return True

    def stop(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=2)


# ============================================================
# HTTP Server + SSE handler
# ============================================================

INDEX_HTML_NAME = "index.html"


class _Handler(BaseHTTPRequestHandler):
    """自定义 HTTP handler:提供 index.html 和 /api/events SSE 流。"""

    # 由外部 set
    bus: AuditEventBus = None  # type: ignore
    root: Path = None  # type: ignore
    index_html: bytes = b""

    def log_message(self, format, *args):
        """静默默认 access log(可被外部 logger 接管)。"""
        # 完全静默,避免刷屏
        pass

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/" or path == "/index.html":
            self._serve_html()
        elif path == "/api/events":
            self._serve_sse()
        elif path == "/api/stats":
            self._serve_stats()
        elif path == "/api/ping":
            self._serve_json({"pong": True, "ts": time.time()})
        else:
            self.send_error(404, "Not Found")

    def _serve_html(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(self.index_html)))
        # 防缓存,开发期方便调试
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(self.index_html)

    def _serve_sse(self):
        """SSE 流:订阅事件总线,持续推送。

        Bug 修复(对抗式 SSE 测试发现):
          - 超时从 15s 降到 5s:加快断连检测(原 15s 太慢)
          - 捕获更广异常(socket.error / ConnectionAbortedError)
          - 在 finally 里 unsubscribes 后,主动关闭 connection hint
        """
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        # 关键:禁用 nginx buffering
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        # 订阅事件
        q = self.bus.subscribe()
        try:
            # 初始连接消息
            self._send_sse({"type": "connected", "data": {
                "root": str(self.root),
                "ts": time.time(),
                "subscribers": self.bus.subscriber_count,
            }})
            # 持续推送,直到客户端断开
            while True:
                try:
                    event = q.get(timeout=5)  # 5s 超时(原 15s 太慢)
                    self._send_sse(event)
                except queue.Empty:
                    # 心跳保活 + 主动检测断连
                    try:
                        self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        # 客户端已断开,正常退出
                        break
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            # 客户端断开
            pass
        finally:
            self.bus.unsubscribe(q)

    def _send_sse(self, event: dict):
        """单条 SSE 消息:event + data 两行。

        Bug 修复:异常向上传播(不再 swallow 异常,让 _serve_sse 的外层 except 接住)
        """
        payload = json.dumps(event, ensure_ascii=False)
        msg = f"event: {event.get('type', 'message')}\ndata: {payload}\n\n"
        self.wfile.write(msg.encode("utf-8"))
        self.wfile.flush()

    def _serve_stats(self):
        """当前统计:总记录、approved/rejected/unauthorized 计数、订阅者数。"""
        stats = {"total": 0, "APPROVED": 0, "REJECTED": 0,
                 "UNAUTHORIZED": 0, "subscribers": self.bus.subscriber_count}
        audit_path = self.root / ".pandaone" / "pandaone.jsonl"
        if audit_path.exists():
            try:
                for line in audit_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        stats["total"] += 1
                        s = rec.get("status", "UNKNOWN")
                        if s in stats:
                            stats[s] += 1
                    except json.JSONDecodeError:
                        continue
            except OSError:
                pass
        self._serve_json(stats)

    def _serve_json(self, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


# ============================================================
# 主入口
# ============================================================

class _PandaoneHTTPServer(ThreadingHTTPServer):
    """仪表盘专用 HTTP server:端口占用是**原子**的,端口不会被别人抢走。

    v0.7.33.1 fix (Windows 端口抢占 / 端口被两个进程共享):
      socketserver 的 TCPServer.allow_reuse_address 默认 = 1 -> server_bind()
      会设 SO_REUSEADDR。而 **Windows** 上 SO_REUSEADDR 的语义和 Linux 不同:
      它允许另一个 socket **抢占本进程(或别的进程)已经 LISTEN 的端口**
      (Linux 上同样的 bind 直接 EADDRINUSE 失败,必须 SO_REUSEPORT 才行)。
      实测(Windows + Python 3.11,端口已被别的 socket 监听时):
        - 不带 SO_REUSEADDR 的 bind -> 失败 errno=10048  (正确识别"被占")
        - 带   SO_REUSEADDR 的 bind -> **成功**             (端口被抢走)
      后果: 同机并发跑两份 pandaone serve(例如并发跑两遍全量测试)时,
            两个进程会"同时拥有"同一端口 -> 请求被随机分给其中一个,
            另一个直接被 RST(WinError 10054) ->
            tests/test_pandax_serve.py 在 Windows 全量并发下偶发 4 个用例红。
      对策: Windows 上关掉 allow_reuse_address —— 端口被别人占着就明确失败,
            自动顺延到下一个端口(不抢);Linux/macOS 保留 True,那里 SO_REUSEADDR
            只放宽 TIME_WAIT 复用、不会抢别人正在监听的端口,保留它还能保证
            "刚退出就重启"不报 Address already in use。
            (实测: Windows 上不带 SO_REUSEADDR 的 bind **不会**被 TIME_WAIT 阻塞,
             所以关掉它不影响快速重启。)
    """

    # Windows: 不设 SO_REUSEADDR,防止抢占别人已监听的端口
    allow_reuse_address = (sys.platform != "win32")

    # 端口被占时向后顺延的最大尝试次数
    port_scan_limit = 20

    def server_bind(self):
        """原子地占用端口: bind 成功才算占到,失败就顺延到下一个端口。

        为什么不再用「先 _find_free_port() 探测、再让 server 重新 bind」:
          探测(bind 完立刻 close)和真正 bind 之间存在 TOCTOU 窗口;
          两个进程并发时会各自探测到同一个"空闲"端口, 然后双双 bind 成功 ->
          同一端口被两个进程共享 -> 请求被随机服务/被 RST。
        这里由 server_bind 自己真正 bind, 成功即占住, 窗口为零。
        """
        if self.allow_reuse_address:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        host, port = self.server_address[:2]
        for offset in range(self.port_scan_limit):
            candidate = port + offset
            try:
                self.socket.bind((host, candidate))
            except OSError:
                continue
            self.server_address = self.socket.getsockname()
            self.server_name = socket.getfqdn(host)
            self.server_port = candidate
            return
        raise RuntimeError(
            f"No free port found in [{port}, {port + self.port_scan_limit})"
        )


def _find_free_port(start: int = 8765, max_tries: int = 20) -> int:
    """从 start 开始找可用端口。

    注意: 这只是"查一下"(探测完就释放),不保证返回的端口在调用方真正 bind 时
    还在空闲 —— 真正占端口请用 _PandaoneHTTPServer.server_bind(原子占用)。
    """
    for offset in range(max_tries):
        port = start + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port found in [{start}, {start + max_tries})")


def start_server(root: Path, port: int = 8765, host: str = "127.0.0.1",
                 open_browser: bool = True) -> ThreadingHTTPServer:
    """启动 pandaone 仪表盘服务器。

    Args:
        root: pandaone 项目根目录
        port: 期望的 HTTP 端口(默认 8765)。**若该端口已被占用,会自动顺延到
              下一个可用端口**(端口冲突自动探测),所以实际端口以返回对象的
              server.server_address[1] 为准,不要假设等于传入的 port。
        host: 绑定地址(默认 127.0.0.1,只本机访问,防 LAN 扫描)
        open_browser: 是否自动打开浏览器
    """
    root = Path(root).resolve()
    bus = AuditEventBus()
    monitor = AuditFileMonitor(root, bus)

    # 注入 bus 到 Handler
    _Handler.bus = bus
    _Handler.root = root
    # index_html 从包内置读取
    try:
        from importlib import resources
        _Handler.index_html = resources.files("pandaone").joinpath(INDEX_HTML_NAME).read_bytes()
    except (ImportError, FileNotFoundError, AttributeError):
        # fallback:文件系统路径
        dev_path = Path(__file__).parent / INDEX_HTML_NAME
        _Handler.index_html = dev_path.read_bytes() if dev_path.exists() else b"<h1>index.html not found</h1>"

    # 找可用端口并**原子占用**(server_bind 内部真正 bind: 占不到就顺延到下一个)
    server = _PandaoneHTTPServer((host, port), _Handler)
    actual_port = server.server_address[1]

    # 启动 watchdog
    has_watchdog = monitor.start()

    # 在后台线程跑 server
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    url = f"http://{host}:{actual_port}"

    print(_t("serve_ok_url", url=url))
    print(_t("serve_info_root", root=root))
    print(_t("serve_info_watch", path=root / '.pandaone' / 'pandaone.jsonl'))
    wd_state = _t("_serve_wd_on") if has_watchdog else _t("_serve_wd_off")
    print(_t("serve_info_watchdog", state=wd_state))
    print(_t("serve_info_stop_hint"))

    if open_browser:
        def _open():
            time.sleep(0.3)
            try:
                import webbrowser
                webbrowser.open(url)
            except Exception:
                pass
        threading.Thread(target=_open, daemon=True).start()

    return server, monitor


def run_blocking(root: Path, port: int = 8765) -> int:
    """同步入口:启动 server 并阻塞,直到 Ctrl+C。"""
    server, monitor = start_server(root, port)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(_t("serve_info_shutdown"))
        monitor.stop()
        server.shutdown()
        server.server_close()
        return 0


if __name__ == "__main__":
    # 命令行调试入口
    import argparse
    ap = argparse.ArgumentParser(description="Pandaone Web 仪表盘")
    ap.add_argument("--root", default=".", help="pandaone 项目根")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    sys.exit(run_blocking(Path(args.root), args.port))