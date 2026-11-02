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
  - **比对内容哈希**（content_sha256）：审批放行的是"这一次改动"，
    不是"这个路径"（否则一次旧审批可无限期放行后续任意改写）
  - 缺记录 / 哈希不一致 → exit 1（拒绝 commit）

内容绑定（A1 盲区修复）
----------------------
  旧实现只做"路径成员判定"：只要这个文件历史上有过一条 APPROVED 记录，
  之后无论内容被改成什么都能提交。实测：把 app.py 完全改写成
  `import os; os.system('echo PWNED')`，hook 与 pandaone ci 都放行。

  现在：写审计记录时落 content_sha256（= git index blob 的 SHA256，
  也就是**这次改动真正要提交的内容**），校验时取 index 里的字节算
  SHA256 与之比对，不一致即拒绝。

  存量记录没有 content_sha256 → 保留"按路径放行"并打印 warn
  （渐进增强：不能因为升级就让所有存量项目的 hook 突然拒绝所有提交）。

  判定逻辑放在 pandaone/audit_binding.py（共享模块），
  本模板是**独立副本**：安装时 audit_binding.py 会被一起拷到 .pandaone/，
  模板优先 import 同目录副本，其次 import 已安装的 pandaone 包。
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
    # 这比硬编码任何人的机器路径都可靠：Git for Windows 装在 C/D/E 盘任意
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
    _hook_no_config / _hook_init_hint / ... 等 key).

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
    "_hook_binding_missing": "[Pandaone] Reject commit: audit content-binding module (audit_binding.py) is missing. Please run pandaone install-hook again.",
    "_hook_legacy_no_hash": "[WARN] Historical approval for {file} is not bound to content (no content_sha256); passing by path this time. Re-audit it to enable content verification.",
    "_hook_reject_content_mismatch": "[Pandaone] Reject commit: the following files were rewritten without a new audit",
    "_hook_mismatch_detail": "  {file} (expected {expected} / actual {actual})",
    "_hook_mismatch_hint": "Please re-audit these files with pandaone write before committing:",
    "_hook_content_unavailable": "[Pandaone] Reject commit: cannot read staged content: {file}",
}


def _load_binding():
    """加载共享的审计内容绑定模块（pandaone/audit_binding.py）。

    优先用**同目录副本**（install-hook 会把 audit_binding.py 一起拷到
    .pandaone/）——它与本模板版本严格一致，不会出现"新模板 + 旧模块"的
    组合；其次用已安装的 pandaone 包。

    两者都拿不到 → 返回 None（调用方 fail closed：拒绝提交）。
    绝不"降级成只查路径"——那等于把 A1 盲区又放回去。
    """
    try:
        import importlib.util
        sibling = Path(__file__).resolve().parent / "audit_binding.py"
        if sibling.is_file():
            spec = importlib.util.spec_from_file_location(
                "pandaone_audit_binding", str(sibling))
            if spec is not None and spec.loader is not None:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                return mod
    except Exception:
        pass
    try:
        from pandaone import audit_binding as mod
        return mod
    except Exception:
        pass
    return None


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

    # 0. 加载共享判定模块（hook 与 pandaone ci 共用同一份逻辑）
    binding = _load_binding()
    if binding is None:
        print("")
        print("================================================================")
        print(t_safe("_hook_binding_missing"))
        print("================================================================")
        sys.exit(1)

    # 1. 读取受保护扩展名
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        protected_exts = cfg.get("protected_extensions", [".py"])
    except Exception as e:
        print(t_safe("_hook_cfg_parse_err", e=e), file=sys.stderr)
        sys.exit(1)

    git_exe = _resolve_git_exe()

    # 2. 读取 git staged 文件
    #    --diff-filter=ACMR：加上 R(rename)/C(copy)。
    #    旧实现只有 "AM"，`git mv a.py b.py` 之后 b.py 不在检查集内 → 改名即逃逸。
    staged = binding.staged_paths(git_exe, repo_root, "ACMR")
    if staged is None:
        print(t_safe("_hook_git_diff_err", stderr="git diff --cached failed"), file=sys.stderr)
        sys.exit(1)

    # 3. 过滤出受保护扩展名
    #    用 dotfile 感知的 effective_suffix（不是 Path(f).suffix）：
    #    Path(".env").suffix == '' → .env 永远不被检查。
    protected_staged = [f for f in staged if binding.effective_suffix(f) in protected_exts]

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

    try:
        records = binding.load_audit_records(audit_path)
    except Exception as e:
        print(t_safe("_hook_audit_read_err", e=e), file=sys.stderr)
        sys.exit(1)

    # 5. 逐个受保护文件做内容绑定校验
    #    关键：取 **index（staged）里的字节**，不是工作区文件。
    #    工作区可能又改了但没 add —— 真正要提交的是 index 里的内容。
    index_map = binding.index_blob_map(git_exe, repo_root)

    missing = []
    mismatched = []
    unreadable = []
    legacy_files = []

    for f in protected_staged:
        content = binding.blob_bytes(git_exe, repo_root, index_map.get(f))
        verdict = binding.verify_content(f, content, records)
        status = verdict.get("status")
        if status == binding.STATUS_NO_RECORD:
            missing.append(f)
        elif status == binding.STATUS_MISMATCH:
            mismatched.append((f, verdict))
        elif status == binding.STATUS_NO_CONTENT:
            unreadable.append(f)
        elif status == binding.STATUS_LEGACY:
            legacy_files.append(f)

    # 5.1 存量记录（无 content_sha256）：按路径放行，但必须提示
    for f in legacy_files:
        print(t_safe("_hook_legacy_no_hash", file=f))

    # 5.2 完全没有任何 APPROVED 记录 → 拒绝（保持原有行为）
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

    # 5.3 取不到待提交内容 → fail closed
    if unreadable:
        print("")
        print("================================================================")
        print(t_safe("_hook_content_unavailable", file=", ".join(unreadable)))
        print("================================================================")
        sys.exit(1)

    # 5.4 内容哈希不一致 → 内容被改写且没有重新审计 → 拒绝
    if mismatched:
        print("")
        print("================================================================")
        print(t_safe("_hook_reject_content_mismatch"))
        print("================================================================")
        print("")
        for f, verdict in mismatched:
            print(t_safe("_hook_mismatch_detail",
                          file=f,
                          expected=verdict.get("expected", ""),
                          actual=verdict.get("actual", "")))
        print("")
        print(t_safe("_hook_mismatch_hint"))
        print(t_safe("_hook_write_example"))
        print("")
        print(t_safe("_hook_bypass_hint"))
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
