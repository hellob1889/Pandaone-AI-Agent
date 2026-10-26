#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pre-commit-check.py
===================
Pandaone AI Agent pre-commit hook 的 Python 校验逻辑（Phase 4.6+）。

由 .git/hooks/pre-commit 调用（shell 脚本只负责传参）。

Phase 10: i18n — 所有 print 走 t()，由 pandaone.i18n 提供。
注意：pre-commit 脚本运行时可能没有安装 pandaone，因此有 fallback 字符串。

第一性原理：
  shell 在处理多行变量和复杂条件时容易出错。把所有审计逻辑放 Python：
  - 读 config.json 获取保护扩展名
  - 读 git staged 文件
  - 对每个 staged 受保护文件查审计日志的 APPROVED 记录
  - 缺记录就 exit 1（拒绝 commit）
"""
import json
import ntpath
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _read_installed_git_hint():
    """读取**安装时**固化的 git 绝对路径 (.pandaone/git_exe.txt)。

    为什么必须有一个"安装时"的来源：
      pre-commit hook 运行在**敌意环境**里（见 shell 包装脚本的说明）。
      Git for Windows 会把 PATH 重写成 MSYS 风格，其中**含非 ASCII 字符的
      目录项**（典型：D:\\软件\\Git\\cmd）会被按错误代码页解码，变成
      mojibake（D:\\鏉瀄ue...\\Git\\cmd）—— 这个路径在磁盘上根本不存在。
      于是：
        - shutil.which("git") 必然返回 None（它按 Windows 语义拼 PATH）；
        - 从 GIT_EXEC_PATH 反推出来的候选**同样带 mojibake**，isfile 必假；
        - 唯一"真值"只剩裸命令 "git"，而 PATH 里同样找不到它 -> WinError 2。

      而**只有安装时刻**（一个 PATH 完好的普通 Windows 进程）能拿到未损坏的
      路径。pandaone install-hook 因此解析一次 git 并写进
      .pandaone/git_exe.txt，本函数负责把它读回来。
    """
    candidates = []
    try:
        candidates.append(Path.cwd() / ".pandaone" / "git_exe.txt")
    except OSError:
        pass
    try:
        # check 脚本被复制到 <repo>/.pandaone/ 下，git_exe.txt 与它同目录
        candidates.append(Path(__file__).resolve().parent / "git_exe.txt")
    except (OSError, TypeError, ValueError):
        pass
    for p in candidates:
        try:
            if p.is_file():
                val = p.read_text(encoding="utf-8", errors="ignore").strip()
                if val:
                    return val
        except OSError:
            continue
    return None


def _git_candidates_from_exec_path(exec_path):
    """从 GIT_EXEC_PATH 反推安装根下的 git 可执行文件候选。

    Git 在 hook 环境里会注入 GIT_EXEC_PATH
    （Windows: <root>\\mingw64\\libexec\\git-core；Linux: /usr/lib/git-core）。
    这里向上**逐级**回溯到安装根，再列举该根下各平台布局里的 git：
      <root>\\cmd\\git.exe           （Git for Windows 的 shim）
      <root>\\bin\\git.exe
      <root>\\mingw64\\bin\\git.exe
      <root>\\mingw64\\cmd\\git.exe
      <root>\\usr\\bin\\git.exe

    比硬编码任何人的安装路径都可靠：装在 C/D/E 盘任意位置都能命中，
    也不必把作者机器的目录结构分发到每个用户机器上。

    注意：Windows 上这条推导路径**可能整体失效**——GIT_EXEC_PATH 里的
    非 ASCII 段在 hook 环境里是 mojibake。此时靠安装时 hint 兜底。
    """
    out = []
    seen = set()
    # 同时按 Windows 与 POSIX 两种分隔符规则回溯：
    #   - Windows 上 os.path 就是 ntpath，天然处理反斜杠
    #   - POSIX 上若收到 Windows 风格路径（跨平台模板文件 + 异常环境），
    #     只有 ntpath 能把它拆开
    for pathmod in (os.path, ntpath):
        try:
            p = pathmod.normpath(exec_path)
        except (TypeError, ValueError):
            continue
        for _ in range(5):
            parent = pathmod.dirname(p)
            if not parent or parent == p:
                break
            p = parent
            for sub in (
                ("cmd", "git.exe"),
                ("bin", "git.exe"),
                ("mingw64", "bin", "git.exe"),
                ("mingw64", "cmd", "git.exe"),
                ("usr", "bin", "git.exe"),
                ("bin", "git"),
                ("cmd", "git"),
            ):
                cand = pathmod.join(parent, *sub)
                if cand not in seen:
                    seen.add(cand)
                    out.append(cand)
    return out


def _where_git():
    """Windows 原生查找：where.exe git（走 Windows 自己的 PATH 语义）。

    与 shutil.which 不同，where.exe 读的是 Windows 原生环境块；
    当 PATH 未被 MSYS 破坏时它能给出未损坏的绝对路径。
    """
    if os.name != "nt":
        return None
    try:
        proc = subprocess.run(
            ["where.exe", "git"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    for line in (proc.stdout or "").splitlines():
        cand = line.strip()
        if cand and os.path.isfile(cand):
            return cand
    return None


def _resolve_git_exe():
    """
    Resolve `git` executable absolute path.

    候选顺序（每个都必须 isfile 才被采用）：
      1. PANDAONE_GIT_EXE      —— 环境变量显式覆盖
      2. .pandaone/git_exe.txt —— **安装时**固化的路径（Windows 上唯一可靠）
      3. GIT_EXECUTABLE        —— git 自身注入的提示
      4. shutil.which("git")   —— PATH 完好时有效（Linux/macOS）
      5. GIT_EXEC_PATH 反推    —— 逐级回溯安装根
      6. where.exe git         —— Windows 原生 PATH 查找
      7. 常见安装位置
      8. "git"                 —— 兜底：留给 PATH 正常的环境

    逐级降级而不是"一失败就报错"：任何一级拿到真实存在的文件即可；
    失效的候选（git 被移动/卸载/换机）会自动落到下一级。
    """
    candidates = []

    env_override = os.environ.get("PANDAONE_GIT_EXE")
    if env_override:
        candidates.append(env_override)

    hint = _read_installed_git_hint()
    if hint:
        candidates.append(hint)

    env_hint = os.environ.get("GIT_EXECUTABLE")
    if env_hint:
        candidates.append(env_hint)

    try:
        which = shutil.which("git")
    except Exception:
        which = None
    if which:
        candidates.append(which)
    # Git 在 hook 环境里会注入 GIT_EXEC_PATH
    # （Windows: <root>\mingw64\libexec\git-core；Linux: /usr/libexec/git-core）
    # -> 从它反推安装根，再找根目录下的 git 可执行文件。
    # 这比硬编码任何人的安装路径都可靠：Git for Windows 装在 C/D/E 盘任意
    # 位置都能命中，也不必把作者机器的目录结构分发到每个用户机器上。
    exec_path = os.environ.get("GIT_EXEC_PATH") or ""
    if exec_path:
        candidates.extend(_git_candidates_from_exec_path(exec_path))
    # Windows 原生 PATH 查找（where.exe 不受 MSYS 路径重写影响时最准）
    where = _where_git()
    if where:
        candidates.append(where)

    # Common Windows install locations
    for d in (
        r"C:\Program Files\Git\cmd\git.exe",
        r"C:\Program Files\Git\mingw64\bin\git.exe",
        r"C:\Program Files (x86)\Git\cmd\git.exe",
        r"C:\Program Files (x86)\Git\mingw64\bin\git.exe",
    ):
        if os.path.exists(d):
            candidates.append(d)
    for c in candidates:
        try:
            if c and os.path.isfile(c):
                return c
        except OSError:
            continue
    return "git"  # 最后兜底：留给 PATH 正常的环境（Linux/macOS）


def t_safe(key: str, **kwargs) -> str:
    """
    安全翻译函数。

    正常路径: 调 pandaone.i18n.t() (含 zh-CN + en 双语, 见 i18n.py 的
    _hook_no_config / _hook_init_hint / ... 等 13 个 key).

    兜底路径: pandaone 未安装 (hook sub-shell PATH 受限时) 用一段极简英文
    占位, 避免再硬编码中文字符串触发 i18n Hardcoded Chinese Audit.
    """
    try:
        from pandaone.i18n import t as _t
        i18n_lang = os.environ.get("PANDAX_LANG", "")
        if i18n_lang in ("zh-CN", "en"):
            from pandaone import i18n
            i18n.set_lang(i18n_lang)
        return _t(key, **kwargs)
    except ImportError:
        # Last-resort fallback: 短英文占位, 真实文案集中在 i18n.py
        return _FALLBACK_EN.get(key, key).format(**kwargs)


# Last-resort English fallback (used only when pandaone.i18n cannot be imported).
# All real strings live in src/pandaone/i18n.py under _hook_* keys.
_FALLBACK_EN = {
    "_hook_no_config": "[Pandaone] Reject commit: .pandaone/config.json not found",
    "_hook_init_hint": "Please run: pandaone init",
    "_hook_cfg_parse_err": "[Pandaone] config.json parse error: {e}",
    "_hook_git_diff_err": "[Pandaone] git diff failed: {stderr}",
    "_hook_git_call_err": "[Pandaone] git call failed: {e}",
    "_hook_no_audit": "[Pandaone] Reject commit: audit log not found",
    "_hook_should_exist": "Expected at: {path}",
    "_hook_audit_read_err": "[Pandaone] read audit log failed: {e}",
    "_hook_reject_no_audit": "[Pandaone] Reject commit: the following files have no APPROVED audit record",
    "_hook_staged_files": "Staged protected files:",
    "_hook_use_pandaone_write": "Please use pandaone write instead of git commit:",
    "_hook_write_example": '  pandaone write --file <FILE> --reason "..." --problem "..." --approach "..."',
    "_hook_bypass_hint": "To bypass audit (not recommended), use: git commit --no-verify",
}


def main():
    repo_root = Path.cwd()
    config_path = repo_root / ".pandaone" / "config.json"
    audit_path = repo_root / ".pandaone" / "pandaone.jsonl"

    if not config_path.exists():
        print("")
        print("================================================================")
        print(t_safe("_hook_no_config"))
        print("================================================================")
        print(t_safe("_hook_init_hint"))
        sys.exit(1)

    # 1. 读取受保护扩展名
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        protected_exts = cfg.get("protected_extensions", [".py"])
    except Exception as e:
        print(t_safe("_hook_cfg_parse_err", e=e), file=sys.stderr)
        sys.exit(1)

    # 2. 读取 git staged 文件
    try:
        r = subprocess.run(
            [_resolve_git_exe(), "diff", "--cached", "--name-only", "--diff-filter=AM"],
            cwd=str(repo_root), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=10,
        )
        if r.returncode != 0:
            print(t_safe("_hook_git_diff_err", stderr=r.stderr), file=sys.stderr)
            sys.exit(1)
        staged = [f.strip().replace("\\", "/") for f in r.stdout.splitlines() if f.strip()]
    except Exception as e:
        print(t_safe("_hook_git_call_err", e=e), file=sys.stderr)
        sys.exit(1)

    # 3. 过滤出受保护扩展名
    protected_staged = [f for f in staged if Path(f).suffix in protected_exts]

    if not protected_staged:
        # 没有受保护文件被 staged, 放行
        sys.exit(0)

    # 4. 读取审计日志的 APPROVED 记录
    if not audit_path.exists():
        print("")
        print("================================================================")
        print(t_safe("_hook_no_audit"))
        print("================================================================")
        print(t_safe("_hook_should_exist", path=audit_path))
        sys.exit(1)

    approved_files = set()
    try:
        with audit_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("status") == "APPROVED":
                        f_norm = str(rec.get("file", "")).replace("\\", "/")
                        approved_files.add(f_norm)
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(t_safe("_hook_audit_read_err", e=e), file=sys.stderr)
        sys.exit(1)

    # 5. 找出未被审计的文件
    missing = []
    for f in protected_staged:
        f_norm = f.replace("\\", "/")
        if f_norm not in approved_files and f not in approved_files:
            missing.append(f)

    if missing:
        print("")
        print("================================================================")
        print(t_safe("_hook_reject_no_audit"))
        print("================================================================")
        print("")
        print(t_safe("_hook_staged_files"))
        for m in missing:
            print(f"  {m}")
        print("")
        print(t_safe("_hook_use_pandaone_write"))
        print(t_safe("_hook_write_example"))
        print("")
        print(t_safe("_hook_bypass_hint"))
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()