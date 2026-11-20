# -*- coding: utf-8 -*-
"""
health_probe.py — status 与 doctor 共用的健康判据（单一事实源）
================================================================

为什么需要这个模块（第一性原理）
--------------------------------
`pandaone status`（仪表盘）和 `pandaone doctor`（自检）回答的是**同一组问题**：

  L1  受保护文件是不是真的锁成只读？
  L2  看门狗是不是真的在跑（而不是 PID 残留假绿）？
  L5  自指纹是不是与基线一致？
  L6  审计日志里有没有真的篡改记录？

历史上这两个命令**各写各的判据**，已经漂移过三次（每一次都是真 bug）：

  1. status 的 L1 传空 config → ``config.get("protected_extensions", [".py"])``
     永远拿到默认的 ``[".py"]`` → 631 个受保护文件在仪表盘上**完全不可见**。
  2. status 的 L2 只查 PID 存活 → 看门狗被强杀后 PID 残留，而 PID 会被系统
     回收复用（别的进程拿到同一个 PID）→ 假绿。
  3. status 的 L5 直接比 hash、丢掉 form → pip 版与 exe 版共存（合法部署行为）
     时误报"不匹配"，用户会以为工具被篡改而不再信任它。

根因不是"忘了同步"，而是**没有共享判据的落点** —— 每加一层就要在两处各写一遍，
第三次漂移只是时间问题。本模块把这 4 个判据各写**一次**，status 与 doctor
都从这里取，新层不会再漂移。

约束
----
1. **纯逻辑 + 只读**：不 import cli（避免循环依赖）、不 print、不改任何文件。
2. **三态语义**（na / ok / fail，另有 warn）：
     na   = 该层**从未启用** → 不是失败，不影响退出码
     ok   = 配置过且通过
     fail = 配置过但坏了
     warn = 通过但基线不可比（例如形态切换、版本升级）
3. 返回值统一是 dict，至少含 ``state`` / ``note`` 两个字段；各判据附加自己的
   统计字段（total / locked / pid / ...）。
"""
from __future__ import annotations

import fnmatch
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

# ============================================================
# 三态常量
# ============================================================

#: 该层从未启用 / 不适用 —— 不是失败
NA = "na"
#: 配置过且检查通过
OK = "ok"
#: 配置过但坏了
FAIL = "fail"
#: 通过但基线不可比（例如形态切换）
WARN = "warn"

#: 项目没有 config.json 时的兜底保护范围。
#: 与 doctor v0.7.34.0 的既有默认值保持一致（改这里必须同步改 doctor 的注释）。
DEFAULT_CONFIG = {
    "protected_extensions": [".py"],
    "exclude_patterns": ["__pycache__", "*.pyc", ".git", ".pandaone"],
}


def _state(state: str, note: str, **extra) -> dict:
    """构造统一形状的判据结果。"""
    out = {"state": state, "note": note}
    out.update(extra)
    return out


# ============================================================
# 1. 项目配置
# ============================================================

def load_project_config(root) -> tuple[dict, str | None]:
    """读 ``.pandaone/config.json``。

    返回 ``(config, err)``：
      - ``config``：dict（文件不存在时用 DEFAULT_CONFIG 兜底）
      - ``err``：None 表示没问题；非 None 表示"文件在，但坏了"
    """
    cfg_path = Path(root) / ".pandaone" / "config.json"
    if not cfg_path.exists():
        return dict(DEFAULT_CONFIG), None
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception as e:
        return dict(DEFAULT_CONFIG), f"unreadable: {e}"
    if not isinstance(data, dict):
        return dict(DEFAULT_CONFIG), "not a JSON object"
    return data, None


def iter_protected_files(root, config: dict) -> list[Path]:
    """枚举项目根下所有受保护扩展名的文件。

    单一事实源：``cli_chunks/part_003.py`` 的 ``_iter_protected_files`` 现在
    转发到这里，status / doctor / lock / ci 共用同一套枚举。

    注意 dotfile：``.env`` 的标准 pathlib 后缀是空串，直接用 ``Path.suffix``
    会让它永远逃过扩展名检查 —— 这里用 audit_binding.effective_suffix
    （dotfile 感知），与 hook / ci 的判定口径完全一致。
    """
    from pandaone.audit_binding import effective_suffix

    root = Path(root)
    protected_exts = set(config.get("protected_extensions", [".py"]))
    exclude_patterns = config.get("exclude_patterns", [])

    files: list[Path] = []
    seen: set[Path] = set()
    for p in root.rglob("*"):
        try:
            if not p.is_file():
                continue
        except OSError:
            continue
        # desktop.ini 是 Windows 的目录图标配置文件（Explorer / 系统自己管理，
        # 不是用户代码）—— 永远不该算受保护文件。
        # 原因: pandaone lock 之后 apply_desktop_icon() 才写它（且必须可写），
        # 算进去会让 L1 永远 FAIL —— 用户执行了开启 L1 的唯一官方命令，
        # doctor / status 反而报红且无解 → 信任崩塌。
        if p.name.lower() == "desktop.ini":
            continue
        if p in seen:
            continue
        try:
            rel = p.relative_to(root)
        except ValueError:
            continue
        if effective_suffix(rel.as_posix()) not in protected_exts:
            continue
        seen.add(p)

        skip = False
        for pat in exclude_patterns:
            if any(fnmatch.fnmatch(part, pat) for part in rel.parts):
                skip = True
                break
            if fnmatch.fnmatch(rel.name, pat):
                skip = True
                break
        if skip:
            continue

        files.append(p)
    return files


# ============================================================
# 2. L1 — 受保护文件锁
# ============================================================

def file_lock_state(root) -> dict:
    """L1 判据：受保护文件是不是**真的**被锁成只读。

    三态：
      - 零受保护文件            → NA（没有可保护的东西，不是失败）
      - 从没跑过 lock（无 lock_modes.json）→ NA（该层未启用）
      - 跑过 lock 但文件又可写了 → FAIL（这才是真的坏了）
    """
    root = Path(root)
    config, err = load_project_config(root)
    if err:
        return _state(FAIL, f"config.json {err}", total=0, locked=0, writable=0)
    try:
        files = iter_protected_files(root, config)
    except Exception as e:
        return _state(FAIL, f"protected-file scan failed: {e}",
                      total=0, locked=0, writable=0)

    total = len(files)
    writable = 0
    for p in files:
        try:
            # 用 st_mode 而不是 os.access —— root 下 os.access 对 444 文件
            # 也返回 True，L1 锁对 root 等于没有。
            if p.stat().st_mode & stat.S_IWUSR:
                writable += 1
        except OSError:
            continue
    locked = total - writable

    if total == 0:
        return _state(NA, "N/A - no protected files in this project (nothing to lock)",
                      total=0, locked=0, writable=0)
    if not (root / ".pandaone" / "lock_modes.json").exists():
        return _state(NA, "N/A - lock never applied (no .pandaone/lock_modes.json)",
                      total=total, locked=locked, writable=writable)
    if writable == 0:
        return _state(OK, f"{total}/{total} protected files locked (read-only)",
                      total=total, locked=locked, writable=writable)
    return _state(FAIL, f"{writable}/{total} protected files writable",
                  total=total, locked=locked, writable=writable)


# ============================================================
# 3. L2 — 看门狗进程
# ============================================================

def pid_alive(pid_text) -> bool:
    """探测 PID 是否存活（跨平台用 psutil.pid_exists）。"""
    try:
        pid = int(str(pid_text).strip())
    except (ValueError, AttributeError):
        return False
    if pid <= 0 or pid > 2**31 - 1:
        return False
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
        try:
            os.kill(pid, 0)
            return True
        except PermissionError:
            return True  # 进程存在但属主不同
        except OSError:
            return False


def process_name(pid):
    """返回 pid 对应进程的**进程名**；查不到返回 None。

    Windows: tasklist /FI "PID eq N" /FO CSV /NH
    POSIX  : /proc/<pid>/comm（取不到再退回 psutil）
    """
    try:
        pid = int(str(pid).strip())
    except Exception:
        return None
    if pid <= 0:
        return None
    if sys.platform.startswith("win"):
        try:
            r = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=15,
            )
        except Exception:
            return None
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if not line or line.upper().startswith("INFO:"):
                continue
            parts = [p.strip().strip('"') for p in line.split(",")]
            if len(parts) >= 2 and parts[1] == str(pid):
                return parts[0]
        return None
    try:
        comm = Path(f"/proc/{pid}/comm")
        if comm.exists():
            return comm.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        pass
    try:
        import psutil
        return psutil.Process(pid).name()
    except Exception:
        return None


def process_cmdline(pid) -> str:
    """返回 pid 的命令行（仅 POSIX 有 /proc）；拿不到返回空串。"""
    try:
        pid = int(str(pid).strip())
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except Exception:
        return ""
    return raw.replace(b"\x00", b" ").decode("utf-8", errors="replace")


def watchdog_process_verdict(name):
    """判断进程名是不是 pandaone 看门狗。

    返回 (verdict, detail)：
      'ok'      —— 明确是 pandaone 进程
      'unknown' —— 名字不足以判断（源码形态下是 python.exe）→ 不据此判失败
      'reused'  —— 明确是别的程序 → PID 被复用 → 判失败

    保守原则: 只有"明确不是看门狗"才判失败。
    源码形态下看门狗是 `python -m pandaone_guard`，进程名只有 python.exe，
    单看名字分不出来 —— 这种情况下要靠 /proc/<pid>/cmdline 补证，
    补不到就只提示"无法核实"，绝不误报（误报一次，用户就不信 doctor 了）。
    """
    n = (name or "").strip().lower()
    if not n:
        return "unknown", ""
    if "pandaone" in n:
        return "ok", n
    stem = n[:-4] if n.endswith(".exe") else n
    if stem in ("python", "pythonw", "python3", "python3w", "py"):
        return "unknown", n
    return "reused", n


def watchdog_alive_notes(pid_text) -> tuple[list, list]:
    """PID 还活着时，校验"这个进程确实是看门狗"（防 PID 复用假绿）。

    返回 (notes, problems)：
      - 进程名明确不是看门狗 → problems 非空（PID 被复用 → 假绿 → 判 FAIL）
      - 名字不足以判断（源码形态是 python.exe）→ 只放 notes，**不**判失败
    """
    name = process_name(pid_text)
    verdict, detail = watchdog_process_verdict(name)
    if verdict == "reused":
        return ([], [f"watchdog pid {pid_text} reused by unrelated process ({detail})"])
    if verdict == "ok":
        return ([f"watchdog alive (pid {pid_text}, {detail})"], [])
    # unknown: 名字不足以判断（源码形态是 python.exe）→ 用 /proc 补证
    cmdline = process_cmdline(pid_text)
    if "pandaone" in cmdline.lower():
        return ([f"watchdog alive (pid {pid_text}, {detail or 'python'})"], [])
    if detail:
        return ([f"watchdog alive (pid {pid_text}, process name {detail} not verifiable)"], [])
    return ([f"watchdog alive (pid {pid_text})"], [])


def watchdog_state(root) -> dict:
    """L2 判据（共享核心）：看门狗是不是真的在跑。

    三态：
      - 从没跑过（既无 .watchdog_pid 也无 watchdog.log）→ NA
      - 跑过但现在死了 / PID 被别的进程复用 → FAIL
      - PID 活着且确实是看门狗 → OK
    """
    root = Path(root)
    pid_path = root / ".pandaone" / ".watchdog_pid"
    log_path = root / ".pandaone" / "watchdog.log"
    if not pid_path.exists() and not log_path.exists():
        return _state(NA, "N/A - watchdog never started (no .watchdog_pid / watchdog.log)",
                      pid="")
    if not pid_path.exists():
        return _state(FAIL, "watchdog NOT running (no .watchdog_pid)", pid="")
    try:
        pid_text = pid_path.read_text(encoding="utf-8").strip()
    except Exception as e:
        return _state(FAIL, f"watchdog pid file unreadable: {e}", pid="")
    if not pid_text:
        return _state(FAIL, "watchdog pid file empty", pid="")
    if not pid_alive(pid_text):
        return _state(FAIL, f"watchdog process NOT alive (pid {pid_text})", pid=pid_text)
    notes, problems = watchdog_alive_notes(pid_text)
    if problems:
        return _state(FAIL, "; ".join(problems), pid=pid_text)
    return _state(OK, "; ".join(notes) or f"watchdog alive (pid {pid_text})", pid=pid_text)


# ============================================================
# 4. L5 — 自指纹
# ============================================================

def fingerprint_state() -> dict:
    """L5 判据（共享核心）：自指纹与基线是否可比 / 一致。

    四态：
      - 无指纹文件 → FAIL（基线缺失；删掉指纹文件就能绕过自检，那不是"首次运行"）
      - form 切换（source ↔ frozen）→ WARN（合法部署行为，不是篡改）
      - 版本变了 → WARN（升级，不是篡改）
      - hash 一致 → OK
      - 同版本同形态但 hash 变了 → FAIL（TAMPERED）
    """
    try:
        from pandaone.cli import compute_fingerprint, FP_PATH
        from pandaone import fp_security as _fpsec
    except Exception as e:
        return _state(FAIL, f"fingerprint module import failed: {e}", stored="", current="")
    if not FP_PATH.exists():
        return _state(FAIL, "no stored fingerprint (baseline missing)", stored="", current="")
    try:
        rec = _fpsec.load_fp_record(path=FP_PATH)
    except Exception as e:
        return _state(FAIL, f"fingerprint file corrupted: {e}", stored="", current="")
    try:
        current = compute_fingerprint()
    except Exception as e:
        return _state(FAIL, f"compute fingerprint failed: {e}",
                      stored=str(rec.get("hash", "")), current="")

    stored_form = rec.get("form") or _fpsec.FORM_SOURCE
    current_form = _fpsec.fp_form()
    stored_version = rec.get("version", "unknown")
    stored_hash = str(rec.get("hash", ""))

    if stored_form != current_form:
        return _state(WARN,
                      f"form switched (stored={stored_form}, current={current_form})"
                      " - baseline not comparable",
                      stored=stored_hash, current=current, version=stored_version)

    try:
        from pandaone.cli import _get_pandaone_version
        current_version = _get_pandaone_version()
    except Exception:
        current_version = None
    # legacy 记录（裸 hex 迁移而来）**没有版本信息** —— 版本"不可比"不是因为
    # 变了，而是因为压根没记。这种情况下按 hash 判定，不能因为版本字段是
    # "0.0.0+legacy" 就报"基线不可比"（那会让存量用户永远看到 WARN）。
    is_legacy = bool(rec.get("migrated"))
    if (not is_legacy and current_version and stored_version
            and stored_version != current_version):
        return _state(WARN,
                      f"version changed (stored=v{stored_version}, current=v{current_version})"
                      " - baseline not comparable",
                      stored=stored_hash, current=current, version=stored_version)

    if stored_hash == current:
        return _state(OK, f"matches stored fingerprint (v{stored_version}, form={current_form})",
                      stored=stored_hash, current=current, version=stored_version)
    return _state(FAIL, f"TAMPERED (stored v{stored_version} != current SHA256)",
                  stored=stored_hash, current=current, version=stored_version)


# ============================================================
# 5. L6 — 篡改检测（审计日志）
# ============================================================

def audit_state(root, fallback=None) -> dict:
    """L6 判据（共享核心）：审计日志里有没有真的篡改记录。

    三态：
      - 没有审计记录 → NA（这一层从没被用过）
      - 项目已 init 却没有审计日志 → FAIL（审计基线被删）
      - 有记录且含 UNAUTHORIZED → FAIL（真篡改）

    ``fallback``：可选的备用日志路径（打包形态下项目目录里没有 .pandaone/）。
    """
    root = Path(root)
    root_log = root / ".pandaone" / "pandaone.jsonl"
    root_cfg = root / ".pandaone" / "config.json"

    if root_log.exists():
        audit_log = root_log
    elif root_cfg.exists():
        return _state(FAIL, "audit log NOT found (audit baseline deleted)",
                      total=0, approved=0, rejected=0, unauthorized=0)
    elif fallback is not None and Path(fallback).exists():
        audit_log = Path(fallback)
    else:
        return _state(NA, "N/A - no audit log yet (clean state)",
                      total=0, approved=0, rejected=0, unauthorized=0)

    records = []
    try:
        for line in audit_log.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except Exception as e:
        return _state(FAIL, f"audit read failed: {e}",
                      total=0, approved=0, rejected=0, unauthorized=0)

    if not records:
        return _state(NA, "N/A - audit log empty (no audit record yet)",
                      total=0, approved=0, rejected=0, unauthorized=0)

    approved = sum(1 for r in records if r.get("status") == "APPROVED")
    rejected = sum(1 for r in records if r.get("status") == "REJECTED")
    unauthorized = sum(1 for r in records if r.get("status") == "UNAUTHORIZED")
    note = (f"audit log: {approved} APPROVED + {rejected} REJECTED "
            f"+ {unauthorized} UNAUTHORIZED")
    counts = {"total": len(records), "approved": approved,
              "rejected": rejected, "unauthorized": unauthorized}
    if unauthorized > 0:
        return _state(FAIL, note + " (unauthorized tampering detected)", **counts)
    return _state(OK, note, **counts)
