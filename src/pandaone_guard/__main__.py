#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pandaone_guard.py
=================
Pandaone AI Agent L2 防御：watchdog 守护进程

第一性原理：
  L1 文件锁可被 shell `attrib -r` 绕过。watchdog 是第二道防线：
  - 监控 .py 文件的修改/创建/移动
  - 无令牌（.audit_token）的写入视为非授权
  - 自动 git checkout 回滚
  - 写 UNAUTHORIZED 审计记录

机制：
  - 用 watchdog.Observer 监听 root 目录
  - PandaXHandler 处理 on_modified / on_created / on_moved
  - 守护进程模式：写 PID 到 .pandaone/.watchdog_pid
  - 优雅退出（KeyboardInterrupt）

用法：
  python pandaone_guard.py --root <project>           # 前台
  python pandaone_guard.py --root <project> --daemon  # 后台
"""
import datetime
import json
import os
import stat
import subprocess
import sys
import time
import uuid
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from pandaone.i18n import t, init as i18n_init


# Bug #23 fix: 同文件同事件在短时间内重复触发时应去重
# 对抗式审查：
#   - 现象：PowerShell Out-File / 一些编辑器对单次写入会触发多次 on_modified
#   - 后果：1 次未授权改动 → 4 条 UNAUTHORIZED 审计记录（噪音污染 + 误报）
#   - 解决：维护 (path, event_type) → last_fire_time 字典，window 秒内视为重复
_DEDUPE_WINDOW_SEC = 2.0


def _effective_suffix(path: Path) -> str:
    """
    Phase 4.6+: 与 cli.py 一致——处理隐藏文件如 .env, .gitignore, .env.local。
    标准 Path.suffix 对 '.env' 返回 ''，但我们认为它是 '.env' 后缀。
    """
    name = path.name
    if name.startswith("."):
        rest = name[1:]
        if "." in rest:
            return "." + rest.rsplit(".", 1)[1]
        return "." + rest
    return path.suffix


class PandaXHandler(FileSystemEventHandler):
    """
    Pandaone 文件监控处理器。
    设计为可独立测试（不需要启动 Observer）。
    Phase 4.6: 不再只看 .py，按 config.json 的 protected_extensions 过滤。
    """

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.audit_path = self.root / ".pandaone" / "pandaone.jsonl"
        self.token_path = self.root / ".pandaone" / ".audit_token"
        self.pid_path = self.root / ".pandaone" / ".watchdog_pid"
        self.exclude_dirs = ("__pycache__", ".git", ".pandaone")

        # Bug #23 fix: 同文件同事件去重（避免 1 次写入产生多条审计记录）
        # key = (rel_path_str, event_type) → last_fire_time (time.time())
        self._recent_events: dict[tuple[str, str], float] = {}

        # 从 config.json 读取 protected_extensions（Phase 4.6）
        config_path = self.root / ".pandaone" / "config.json"
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
                self.protected_extensions = set(config.get("protected_extensions", [".py"]))
                # Phase 5: 二进制保护扩展名
                self.binary_protected_extensions = set(config.get("binary_protected_extensions", []))
                self.binary_snapshots_path = self.root / ".pandaone" / "binary_snapshots.json"
                self.binary_snapshots = {}
                if self.binary_snapshots_path.exists():
                    try:
                        self.binary_snapshots = json.loads(
                            self.binary_snapshots_path.read_text(encoding="utf-8")
                        )
                    except Exception:
                        pass
            except Exception:
                self.protected_extensions = {".py"}
                self.binary_protected_extensions = set()
                self.binary_snapshots = {}
        else:
            self.protected_extensions = {".py"}
            self.binary_protected_extensions = set()
            self.binary_snapshots = {}

    # ---------------- 内部工具 ----------------

    def _is_protected_file(self, path: Path) -> bool:
        """Phase 4.6 + 5: 检查文件后缀是否在 protected_extensions 或 binary_protected_extensions 列表中"""
        eff = _effective_suffix(path)
        return eff in self.protected_extensions or eff in self.binary_protected_extensions

    def _is_binary_file(self, path: Path) -> bool:
        """Phase 5: 检查文件是否受二进制快照保护"""
        return _effective_suffix(path) in self.binary_protected_extensions

    def _binary_snapshot_match(self, path: Path) -> bool:
        """Phase 5: 当前文件 SHA256 是否与 snapshot 匹配"""
        import hashlib
        rel = str(path.relative_to(self.root)).replace("\\", "/")
        expected_sha = self.binary_snapshots.get(rel)
        if expected_sha is None:
            return False  # 没有 snapshot = 未跟踪
        try:
            actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return True  # 读失败按"未变化"处理
        return actual_sha == expected_sha

    def _is_excluded(self, path: Path) -> bool:
        """排除 __pycache__、_tmp_*、.git、.pandaone 等"""
        try:
            rel = path.relative_to(self.root)
        except ValueError:
            return True
        for part in rel.parts:
            if part in self.exclude_dirs:
                return True
            if part.startswith("_tmp_") or part.startswith("_fix"):
                return True
        return False

    def _has_audit_token(self) -> bool:
        return self.token_path.exists()

    def _log_unauthorized(self, file_path: Path, detection: str, action: str):
        """写 UNAUTHORIZED 审计记录"""
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "id": f"audit_{uuid.uuid4().hex[:8]}",
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "UNAUTHORIZED",
            "file": str(file_path.relative_to(self.root)),
            "detection": detection,
            "action": action,
        }
        with self.audit_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _git_checkout(self, file_path: Path) -> bool:
        """从 git HEAD 回滚单个文件"""
        try:
            rel = str(file_path.relative_to(self.root))
            r = subprocess.run(
                ["git", "checkout", "HEAD", "--", rel],
                cwd=str(self.root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            return r.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            print(t("_guard_git_checkout_fail", err=e), flush=True)
            return False

    def _auto_lock(self, file_path: Path):
        """自动锁定新创建的 .py 文件"""
        try:
            current = file_path.stat().st_mode
            readonly = current & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH
            os.chmod(file_path, readonly)
            print(t("_guard_auto_lock", name=file_path.name), flush=True)
        except OSError as e:
            print(t("_guard_auto_lock_fail", file=file_path, err=e), flush=True)

    # ---------------- watchdog 事件 ----------------

    def _is_duplicate_event(self, path: Path, event_type: str) -> bool:
        """
        Bug #23 fix: 判断 (path, event_type) 是否在去重窗口内已触发过。

        返回 True 表示应跳过此次处理（重复事件）。
        同时更新 last_fire_time 为当前时间。
        """
        try:
            rel = str(path.relative_to(self.root)).replace("\\", "/")
        except ValueError:
            rel = str(path)

        key = (rel, event_type)
        now = time.time()
        last = self._recent_events.get(key)
        if last is not None and (now - last) < _DEDUPE_WINDOW_SEC:
            # 窗口内重复 → 跳过
            return True
        self._recent_events[key] = now
        # 简单清理：超过窗口 10× 的旧条目移除（防内存泄漏）
        cutoff = now - _DEDUPE_WINDOW_SEC * 10
        stale = [k for k, t in self._recent_events.items() if t < cutoff]
        for k in stale:
            self._recent_events.pop(k, None)
        return False

    def on_modified(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if not self._is_protected_file(path) or self._is_excluded(path):
            return
        if self._has_audit_token():
            return  # 合法写入（pandaone write 已设令牌）
        # Bug #23 fix: 窗口内重复事件直接跳过
        if self._is_duplicate_event(path, "modified"):
            return

        # Phase 5: 二进制文件用 SHA256 对比（不能用 chmod 回滚到旧版本除非 git 有历史）
        if self._is_binary_file(path):
            if self._binary_snapshot_match(path):
                # 文件 SHA256 与 snapshot 一致 = 未变化 = 不是攻击
                return
            print(f"[UNAUTHORIZED] binary on_modified: {path.name} (SHA256 mismatch)", flush=True)
            reverted = self._git_checkout(path)
            self._log_unauthorized(
                path,
                "watchdog: binary file modified, snapshot mismatch",
                "reverted from git HEAD" if reverted else "revert failed",
            )
            return

        # 文本文件路径（原有逻辑）
        # Bug #24 fix: print 显式 flush（前台 watch 输出不被 Python 缓冲）
        print(f"[UNAUTHORIZED] on_modified: {path.name}", flush=True)
        reverted = self._git_checkout(path)
        self._log_unauthorized(
            path,
            "watchdog: on_modified without audit token",
            "reverted from git HEAD" if reverted else "revert failed",
        )

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if not self._is_protected_file(path) or self._is_excluded(path):
            return
        # 新受保护文件 → 自动锁定（防 agent 直接创建未审计文件）
        self._auto_lock(path)

    def on_moved(self, event):
        """检测 delete + create 同名文件的攻击"""
        if event.is_directory:
            return
        path = Path(event.dest_path)
        if not self._is_protected_file(path) or self._is_excluded(path):
            return
        if self._has_audit_token():
            return
        # Bug #23 fix: 窗口内重复事件直接跳过
        if self._is_duplicate_event(path, "moved"):
            return

        print(f"[UNAUTHORIZED] on_moved: {path.name}", flush=True)
        reverted = self._git_checkout(path)
        self._log_unauthorized(
            path,
            "watchdog: on_moved without audit token",
            "reverted from git HEAD" if reverted else "revert failed",
        )


# ============================================================
# 守护进程入口
# ============================================================
def run_watchdog(root: Path, daemon: bool = False):
    """启动 watchdog 监控"""
    root = Path(root).resolve()
    pid_path = root / ".pandaone" / ".watchdog_pid"
    pid_path.parent.mkdir(parents=True, exist_ok=True)

    # 探测 git 路径并加入 PATH（PyInstaller 环境常缺失）
    _ensure_git_in_path()

    handler = PandaXHandler(root)
    observer = Observer()
    observer.schedule(handler, str(root), recursive=True)

    pid_path.write_text(str(os.getpid()), encoding="utf-8")

    observer.start()
    try:
        # Bug #24 fix: print 显式 flush（前台 watch 输出不被 Python 缓冲）
        print(t("_guard_started", root=root), flush=True)
        print(t("_guard_pid", pid=os.getpid(), path=pid_path), flush=True)
        if daemon:
            print(t("_guard_daemon_hint"), flush=True)
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n" + t("_guard_signaled"), flush=True)
        observer.stop()
    finally:
        observer.join()
        # 清理 PID 文件
        if pid_path.exists():
            try:
                pid_path.unlink()
            except OSError:
                pass


def _ensure_git_in_path():
    """探测 git 路径并加入 PATH（PyInstaller 环境常缺失）

    Bug #40 fix (v0.7.10): 不再硬编码作者机器路径 `D:\\软件\\Git\\cmd`。
    改为调用 git_installer._windows_candidate_dirs() 单一来源
    (基于 %ProgramFiles% / %LOCALAPPDATA% / 注册表 InstallPath)。
    """
    import shutil

    if shutil.which("git"):
        return  # 已在 PATH

    # 常见路径探测 (Windows 走 git_installer 派生，非 Windows 退到 PATH)
    if os.name == "nt":
        try:
            from pandaone.git_installer import _windows_candidate_dirs
            candidates = _windows_candidate_dirs()
        except ImportError:
            candidates = [
                r"C:\Program Files\Git\cmd",
                r"C:\Program Files (x86)\Git\cmd",
                r"C:\Program Files\Git\bin",
                r"C:\Git\cmd",
            ]
    else:
        candidates = []

    for cand in candidates:
        if Path(cand, "git.exe").exists():
            os.environ["PATH"] = cand + os.pathsep + os.environ.get("PATH", "")
            print(t("_guard_git_found", path=cand), flush=True)
            return

    print(t("_guard_no_git"), flush=True)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Pandaone L2 watchdog 守护进程")
    parser.add_argument("--root", default=".", help="项目根目录")
    parser.add_argument("--daemon", action="store_true", help="后台运行")
    args = parser.parse_args()
    run_watchdog(Path(args.root), daemon=args.daemon)


if __name__ == "__main__":
    main()