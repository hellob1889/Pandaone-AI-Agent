"""
fp_security.py — L5 自指纹 + 指纹密码体系

第一性原理
----------
L5 防御 = pandaone 自身的完整性保护。
  如果 agent 修改了 pandaone 本体来跳过审计，必须能检测到。

所以指纹必须覆盖**能被用来改变行为的全部文件**，而不只是 .py：
  - v0.7.9~v0.7.19：只哈希 cli.py 一个文件 → 改任何一个 chunk 都绕过
  - v0.7.20~v0.7.22：哈希 pandaone/ 下全部 *.py → 改资源文件仍绕过
  - v0.7.23（本文件）：哈希**整个包目录**（pandaone/ + pandaone_guard/）
    的全部文件 → templates/、installer/、index.html、banner.txt、*.ico
    全都在覆盖范围内

密码体系（用户明确要求：必须保留默认值 0000）
------------------------------------------------
默认密码**保持 "0000" 不变**（本地单用户的零摩擦体验），但用户可以自行改密：
  1. 环境变量 PANDAONE_FP_PASSWORD   （推荐；新名）
  2. 环境变量 PANDAX_FP_PASSWORD      （旧名，**已废弃**，仅为兼容保留）
  3. 配置文件 ~/.pandaone/fp_password  （用户自设，0600 权限）
  4. 默认 "0000"                       （兜底，必须存在）

比较一律走 hmac.compare_digest（常量时间），避免时序侧信道；
连续失败 N 次进入短时锁定，防暴力猜。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: 默认指纹密码。**必须保留** —— 本地单用户零摩擦，用户可自行改密。
DEFAULT_FP_PASSWORD = "0000"

#: 新环境变量名（推荐）
ENV_FP_PASSWORD = "PANDAONE_FP_PASSWORD"
#: 旧环境变量名（品牌重命名前遗留）。**废弃别名**，仅为不打断存量脚本而保留。
ENV_FP_PASSWORD_LEGACY = "PANDAX_FP_PASSWORD"

#: 连续失败多少次后锁定
FP_MAX_FAILURES = 5
#: 锁定时长（秒）
FP_LOCK_SECONDS = 900  # 15 分钟
#: 自定义密码的最短长度
FP_MIN_PASSWORD_LENGTH = 4

#: 指纹文件（json: {version, hash, form, stored_at}）
DEFAULT_FP_PATH = Path.home() / ".pandaone_fp.txt"

#: 运行形态标识。
#:   "source" —— 源码树 / pip 安装（同一批文件的指纹）
#:   "frozen" —— PyInstaller 打包的 .exe（文件集合不同，指纹必然不同）
#:
#: 形态切换（用户把源码版换成 .exe 版，或反过来）是**合法部署行为**，
#: 不能当成篡改 —— 否则装完 .exe 第一次运行就会被 L5 锁死。
FORM_SOURCE = "source"
FORM_FROZEN = "frozen"


def fp_form() -> str:
    """返回当前运行形态标识。"""
    return FORM_FROZEN if getattr(sys, "_MEIPASS", None) else FORM_SOURCE


# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------

def fp_password_file() -> Path:
    """用户自定义指纹密码的存放位置。"""
    return Path.home() / ".pandaone" / "fp_password"


def fp_lock_file() -> Path:
    """失败计数 / 锁定状态文件。"""
    return Path.home() / ".pandaone" / "fp_lock.json"


# ---------------------------------------------------------------------------
# 密码
# ---------------------------------------------------------------------------

def get_fingerprint_password() -> str:
    """读取 CLI 自指纹更新密码。

    优先级（高 → 低）：
      1. 环境变量 ``PANDAONE_FP_PASSWORD``（新名，推荐）
      2. 环境变量 ``PANDAX_FP_PASSWORD``（旧名，**已废弃**，仅兼容）
      3. 配置文件 ``~/.pandaone/fp_password``（用户自设）
      4. 默认 ``"0000"``

    说明：返回动态值而非常量，"密码走变量"；默认值保留保证零摩擦。
    """
    v = os.environ.get(ENV_FP_PASSWORD)
    if v:
        return v
    legacy = os.environ.get(ENV_FP_PASSWORD_LEGACY)
    if legacy:
        return legacy
    try:
        p = fp_password_file()
        if p.is_file():
            text = p.read_text(encoding="utf-8").strip()
            if text:
                return text
    except OSError:
        pass
    return DEFAULT_FP_PASSWORD


def verify_password(given: str, expected: str) -> bool:
    """常量时间比较密码（hmac.compare_digest），避免时序侧信道。"""
    try:
        return hmac.compare_digest(
            str(given).encode("utf-8"), str(expected).encode("utf-8")
        )
    except (TypeError, ValueError):
        return False


def set_fingerprint_password(new_password: str) -> Path:
    """把用户自设的指纹密码写到 ``~/.pandaone/fp_password``（0600）。

    返回实际写入的路径。密码为空时抛 ValueError。
    """
    if new_password is None or str(new_password) == "":
        raise ValueError("password must not be empty")
    p = fp_password_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(new_password), encoding="utf-8")
    try:
        os.chmod(p, 0o600)  # POSIX；Windows 上静默忽略
    except OSError:
        pass
    return p


def clear_fingerprint_password() -> Path:
    """删掉用户自设密码，回落到默认 0000。"""
    p = fp_password_file()
    try:
        if p.is_file():
            p.unlink()
    except OSError:
        pass
    return p


# ---------------------------------------------------------------------------
# 失败锁定
# ---------------------------------------------------------------------------

def read_lock_state() -> dict:
    """读锁定状态文件；损坏时按空状态处理。"""
    try:
        data = json.loads(fp_lock_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_lock_state(data: dict) -> None:
    """写锁定状态文件；失败不影响主流程。"""
    try:
        p = fp_lock_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def fp_lock_state() -> tuple[bool, int]:
    """返回 ``(是否处于锁定中, 剩余秒数)``。"""
    data = read_lock_state()
    try:
        until = float(data.get("locked_until", 0) or 0)
    except (TypeError, ValueError):
        until = 0.0
    now = time.time()
    if until > now:
        return True, int(until - now)
    return False, 0


def register_failure() -> int:
    """记录一次密码错误；达到阈值则进入锁定。

    返回本轮之后的累计失败次数。
    """
    data = read_lock_state()
    try:
        n = int(data.get("fail_count", 0) or 0) + 1
    except (TypeError, ValueError):
        n = 1
    if n >= FP_MAX_FAILURES:
        data["fail_count"] = 0
        data["locked_until"] = time.time() + FP_LOCK_SECONDS
        data["locked_at"] = time.time()
    else:
        data["fail_count"] = n
    write_lock_state(data)
    return n


def clear_failures() -> None:
    """密码正确 → 清零失败计数（并解除已过期的锁定）。"""
    write_lock_state({"fail_count": 0})


def reset_lock() -> None:
    """无条件解除锁定（用户忘记密码时的自救出口）。"""
    write_lock_state({"fail_count": 0})


# ---------------------------------------------------------------------------
# 指纹
# ---------------------------------------------------------------------------

def fingerprint_roots() -> list[Path]:
    """返回参与指纹计算的两个包目录：pandaone/ 与 pandaone_guard/。

    用 importlib 定位而不是推算 parents —— 已安装形态
    (``site-packages/pandaone/...``) 与源码形态 (``src/pandaone/...``)
    的层级完全不同，推算会错。
    """
    import importlib.util

    roots: list[Path] = []

    # PyInstaller frozen 环境：模块被编译进 PYZ，磁盘上没有 .py 源码树，
    # find_spec() 的 spec.origin 会指向 _MEIPASS 根而不是包目录。
    # 打包时我们把整个包树以数据形式复制到 _MEIPASS/<pkg>/，
    # 所以 frozen 下直接按这个布局定位，作用域与源码形态保持一致。
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        base = Path(meipass)
        for pkg in ("pandaone", "pandaone_guard"):
            d = base / pkg
            if d.is_dir():
                roots.append(d.resolve())
    else:
        for pkg in ("pandaone", "pandaone_guard"):
            try:
                spec = importlib.util.find_spec(pkg)
            except (ImportError, ValueError):
                continue
            if spec is None:
                continue
            locs = getattr(spec, "submodule_search_locations", None)
            if locs:
                try:
                    roots.append(Path(list(locs)[0]).resolve())
                    continue
                except (IndexError, TypeError):
                    pass
            if spec.origin:
                roots.append(Path(spec.origin).resolve().parent)
    # 去重 + 保序
    seen: set[Path] = set()
    out: list[Path] = []
    for r in roots:
        if r not in seen and r.is_dir():
            seen.add(r)
            out.append(r)
    return out


#: 参与指纹的文件排除规则（相对路径任一段命中即排除）
_EXCLUDE_DIRS = {"__pycache__", ".git", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
_EXCLUDE_SUFFIX = {".pyc", ".pyo", ".pyd"}
_EXCLUDE_NAMES = {".DS_Store", "Thumbs.db"}


def _iter_manifest_files(root: Path) -> list[str]:
    """列出 root 下参与指纹的文件（相对路径，正斜杠分隔，已排序）。"""
    files: list[str] = []
    for p in root.rglob("*"):
        try:
            if not p.is_file():
                continue
            rel = p.relative_to(root)
            if any(part in _EXCLUDE_DIRS for part in rel.parts):
                continue
            if p.suffix.lower() in _EXCLUDE_SUFFIX:
                continue
            if p.name in _EXCLUDE_NAMES:
                continue
            files.append(rel.as_posix())
        except OSError:
            continue
    files.sort()
    return files


def compute_fingerprint() -> str:
    """计算整个包目录的聚合 SHA256 指纹。

    覆盖范围：pandaone/ 与 pandaone_guard/ 两个包目录下的**全部文件**
    （.py + templates/ + installer/ + index.html + banner.txt + *.ico …）。

    排除：__pycache__/、*.pyc、.git/ 等运行时/工具产物 —— 它们随时间变化，
    纳入会让指纹每次运行都不同，等于自我失效。

    聚合方式：对每个文件依次喂入 ``pkg\\x00relpath\\x00content\\x00``，
    文件顺序按 (包名, 相对路径) 排序 → 确定性、可复现。
    改名 / 增删文件 / 改内容 都会改变结果。
    """
    roots = fingerprint_roots()
    h = hashlib.sha256()
    entries: list[tuple[str, str, Path]] = []
    for root in roots:
        pkg_name = root.name
        for rel in _iter_manifest_files(root):
            entries.append((pkg_name, rel, root / rel))
    entries.sort(key=lambda e: (e[0], e[1]))
    for pkg_name, rel, f in entries:
        h.update(pkg_name.encode("utf-8"))
        h.update(b"\x00")
        h.update(rel.encode("utf-8"))
        h.update(b"\x00")
        try:
            h.update(f.read_bytes())
        except OSError:
            h.update(b"<unreadable>")
        h.update(b"\x00")
    return h.hexdigest()


def fingerprint_scope() -> dict:
    """返回指纹覆盖范围摘要（供 doctor / --version 自检展示）。"""
    roots = fingerprint_roots()
    per_pkg = {}
    total = 0
    for root in roots:
        n = len(_iter_manifest_files(root))
        per_pkg[root.name] = n
        total += n
    return {"packages": per_pkg, "file_count": total}


# ---------------------------------------------------------------------------
# 指纹文件读写（json 格式，兼容旧裸 hex）
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def save_fp(version: str, hash_hex: str, path: Path | None = None,
            form: str | None = None) -> None:
    """存指纹到 path（默认 ``~/.pandaone_fp.txt``），json 格式。

    ``form`` 缺省取当前运行形态（source / frozen）。
    """
    p = Path(path) if path is not None else DEFAULT_FP_PATH
    data = {
        "version": version,
        "hash": hash_hex,
        "form": form or fp_form(),
        "stored_at": _now_iso(),
    }
    p.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_fp_record(path: Path | None = None) -> dict:
    """读指纹完整记录。

    Returns:
        ``{"version": str, "hash": str, "form": str, "stored_at": str,
           "migrated": bool}``

    旧记录没有 ``form`` 字段 → 按 ``"source"`` 处理（历史指纹都来自
    源码树 / pip 安装）。旧裸 hex 格式 → ``migrated=True``。
    """
    p = Path(path) if path is not None else DEFAULT_FP_PATH
    raw = p.read_text(encoding="utf-8").strip()
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and "version" in data and "hash" in data:
            rec = dict(data)
            rec.setdefault("form", FORM_SOURCE)
            rec["migrated"] = False
            return rec
    except (ValueError, json.JSONDecodeError):
        pass
    if len(raw) == 64 and all(c in "0123456789abcdef" for c in raw.lower()):
        return {
            "version": "0.0.0+legacy",
            "hash": raw,
            "form": FORM_SOURCE,
            "migrated": True,
        }
    raise ValueError(f"FP file corrupted: {raw[:80]!r}")


def load_fp(path: Path | None = None) -> tuple[str, str, bool]:
    """读指纹，兼容旧裸 hex + 新 json 两种格式。

    Returns:
        ``(version, hash, migrated)``；migrated=True 表示从旧裸 hex 迁移。
    """
    rec = load_fp_record(path)
    return rec["version"], rec["hash"], bool(rec.get("migrated", False))
