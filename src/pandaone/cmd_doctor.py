# -*- coding: utf-8 -*-
"""
cmd_doctor.py — `pandaone doctor` 子命令 (PR #28)
============================================

第一性原理:
  - cli.py 93KB 超大,改它要拆 chunks。MCP push 也有限制。
  - 所以 doctor 子命令做成独立模块,在 __main__.py 里 monkey-patch 注册。
  - 对外接口: cmd_doctor(args) 函数 + add_doctor_parser(sub) 函数。

对抗式审查:
  - Q: 为什么不直接改 cli.py?
    A: cli.py 84KB,MCP create_or_update_file 单次推送限制 ~24KB,
       全量推送会被截断。monkey-patch 是规避推送限制的最稳方案。
  - Q: monkey-patch 可靠吗?
    A: Python dict 引用语义保证。cli.COMMANDS['doctor'] = cmd_doctor
       改的是同一个 dict 对象。cli.main() 调 COMMANDS.get(args.command)
       能看到 doctor。

============================================================
v0.7.34.0: 从「存在性体检」升级为「真实可执行性体检」
============================================================
起因（真机安装回归实测，不是推理）:
  - doctor 报 `[OK] L3_pre_commit_hook`，但 `pandaone install-hook` 在 exe 形态下
    完全跑不起来（`invalid choice: 'pandaone.install_hook'` —— 冻结后
    sys.executable 指向 exe 自身，没有 "-m 模块" 语义）。
  - 根因: **L3 只检查"hook 文件在不在"，不检查"安装命令能不能真的跑"**。
  - 审计结论: 8 层里 5 层是存在性判定或查错了对象，只有 L5/L8 做了真检查。
  - 更严重: 即使各层判成 FAIL，`overall_ok` 和退出码也**不吃层级失败** ——
    doctor 照样打印"全部正常"、exit 0。

本版改动（P0~P6）:
  P0 汇总层吃层级失败
     - 新增 `--root`（默认 cwd），所有项目级检查基于它，不再绑死 cwd
     - `overall_ok` = git ok AND python ok AND **所有适用层 ok**
       （显式标记 N/A 的层不参与判定）
     - 退出码新增 3 = 有层级 FAIL（1=缺 git / 2=Python 过旧 语义不变）
     - 层级失败时不再打印"全部正常"横幅，改成列出待处理的层
  P1 L3 变成真检（原来只看 git 装没装）
     a) .git/hooks/pre-commit 存在
     b) 归属校验: 内容含 "Pandaone" 标识（判据同 install_hook.uninstall_hook）
     c) LF-only + 无 BOM（Windows CRLF 会让 bash hook 完全失效）
     d) .pandaone/pre-commit-check.py 存在且能 compile()
     e) install-hook 模块在当前形态可加载（防 frozen 回归）
     f) .pandaone/config.json 的 protected_extensions 非空
  P2 L2 变成真检（原来只看 git 装没装）
     - watchdog 可 import（从 L4 挪过来，它是 L2 的真依赖）
     - git 可执行（_find_git_executable + _can_run_git）
     - 有 baseline commit（没有它 watchdog 的 git checkout 回滚必然失败）
     - watchdog 进程存活（复用 cli_chunks/part_004.py 的 _pid_alive）
     - 冻结形态: <exe 同级>/pandaone_guard.exe 在位
  P3 L1 变成真检（原来是无条件 True 的字面量）
     - 复用 cli_chunks/part_003.py 的 _iter_protected_files 枚举
     - 复用 cli_chunks/part_004.py cmd_status 的锁定计数算法（st_mode & S_IWUSR）
  P4 L6 三态计数（原来漏掉 UNAUTHORIZED —— 那才是 watchdog 抓到的真篡改）
  P5 L4 查对对象: 项目 README 摘要（load_readme_summary），不是 import watchdog
  P6 L5 不误报: 先比 form 再比 hash；无指纹文件 = FAIL（基线缺失）

层级结果 schema:
  {"ok": bool, "note": str, "na": bool(可选), "warn": bool(可选)}
  - na=True  → 该层在当前环境**不适用**，不参与 overall_ok 判定
  - warn=True→ 通过但有提醒（例如 L5 形态切换），不参与失败判定
  note 一律是英文技术描述（与既有 L1/L2/L3 note 一致），不走 i18n。
"""
from __future__ import annotations

import json as _json
import shutil as _shutil
import stat as _stat
import subprocess as _subprocess
import sys as _sys
from pathlib import Path as _Path


# ============================================================
# 0. 通用工具
# ============================================================

#: 层级结果里的显式标记
_NA = "na"
_WARN = "warn"


def _layer(ok: bool, note: str, na: bool = False, warn: bool = False) -> dict:
    """构造一个层级结果 dict。

    ok   —— 该层是否通过（na=True 时恒为 True，不参与失败判定）
    note —— 人类可读说明（英文技术描述，不走 i18n）
    na   —— 该层在当前环境**不适用**（显式标记，排除出 overall_ok）
    warn —— 通过但有提醒（例如 L5 形态切换，基线不可比）
    """
    info = {"ok": bool(ok), "note": note}
    if na:
        info[_NA] = True
    if warn:
        info[_WARN] = True
    return info


def _na_layer(note: str) -> dict:
    """显式标记"不适用"的层。"""
    return _layer(True, note, na=True)


def _resolve_root(root=None) -> _Path:
    """把 --root 参数解析成绝对路径。

    为什么要防 mock.Mock(): 调用方（测试 / cmd_setup）可能传 SimpleNamespace，
    也可能传 mock.Mock() —— 未显式设置的属性访问会返回 truthy 的 Mock 对象，
    直接 _Path(Mock) 会抛 TypeError。
    """
    if isinstance(root, _Path):
        return root.resolve()
    if isinstance(root, str) and root:
        return _Path(root).resolve()
    return _Path.cwd()


def _read_json(path: _Path):
    """读 JSON 文件，返回 (data, err)。err 为 None 表示读成功。"""
    try:
        return _json.loads(path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, "NOT found"
    except Exception as e:
        return None, f"unreadable: {e}"


def _git_executable():
    """返回可用的 git 路径；找不到返回 None。

    复用 git_installer._find_git_executable（PATH + Windows 候选目录 + 注册表）。
    """
    try:
        from pandaone.git_installer import _find_git_executable
    except Exception:
        return None
    try:
        return _find_git_executable()
    except Exception:
        return None


def _find_readme(root: _Path):
    """找项目 README（README.md / readme.md / README.rst ...）。找不到返回 None。"""
    for name in ("README.md", "readme.md", "README.rst", "README.txt", "README"):
        p = root / name
        if p.is_file():
            return p
    try:
        for p in sorted(root.iterdir()):
            if p.is_file() and p.name.lower().startswith("readme"):
                return p
    except OSError:
        pass
    return None


# ============================================================
# 1. 各层真检
# ============================================================

def _check_layer1_file_lock(root: _Path) -> dict:
    """v0.7.34.0: L1 真检 —— 受保护文件是不是**真的**被锁成只读。

    之前是硬编码字面量 {"ok": True, "note": "python-only (attrib/chmod)"} ——
    无条件 True，锁没锁、锁了多少完全看不出来。

    复用点:
      - 枚举: pandaone.cli._iter_protected_files
        （= cli_chunks/part_003.py 的实现，按 config 的 protected_extensions
          + exclude_patterns 过滤）
      - 计数算法: cli_chunks/part_004.py cmd_status 的 locked/unlocked 统计
        （用 st_mode & stat.S_IWUSR 判定，不用 os.access —— root 下 os.access
          对 444 文件也返回 True，L1 锁对 root 等于没有）
    """
    config_path = root / ".pandaone" / "config.json"
    config = {}
    if config_path.exists():
        data, err = _read_json(config_path)
        if err:
            return _layer(False, f"config.json {err}")
        if isinstance(data, dict):
            config = data
    else:
        # 没 init 过: 用项目默认保护范围兜底
        config = {
            "protected_extensions": [".py"],
            "exclude_patterns": ["__pycache__", "*.pyc", ".git", ".pandaone"],
        }
    try:
        from pandaone.cli import _iter_protected_files
    except Exception as e:
        return _layer(False, f"protected-file enumerator unavailable: {e}")
    try:
        files = _iter_protected_files(root, config)
    except Exception as e:
        return _layer(False, f"protected-file scan failed: {e}")
    total = len(files)
    writable = 0
    for p in files:
        try:
            if p.stat().st_mode & _stat.S_IWUSR:
                writable += 1
        except OSError:
            continue
    if total > 0 and writable == 0:
        return _layer(True, f"{total}/{total} protected files locked (read-only)")
    return _layer(False, f"{writable}/{total} protected files writable")


def _check_layer2_watchdog(root: _Path) -> dict:
    """v0.7.34.0: L2 真检 —— watchdog 回滚是不是**真的**能跑。

    复用点:
      - git 探测: git_installer._find_git_executable + _can_run_git
      - 进程存活: pandaone.cli._pid_alive（= cli_chunks/part_004.py 的实现）
    """
    problems = []
    notes = []

    # (1) watchdog 是 L2 的真依赖 —— 从 L4 挪过来（L4 查错了对象）
    try:
        import watchdog  # noqa: F401
        notes.append("watchdog importable")
    except ImportError as e:
        problems.append(f"watchdog NOT installed ({e})")

    # (2) git 必须**可执行**（不只是"装了"）
    git_exe = _git_executable()
    if git_exe is None:
        # 没有 git → L2 整个机制不可用 → 显式 N/A
        # （缺 git 由顶层 git 检查 + exit 1 负责，不重复算层失败）
        return _na_layer("N/A - requires git (L2 watchdog rollback disabled)")
    try:
        from pandaone.git_installer import _can_run_git
        if not _can_run_git(git_exe):
            problems.append(f"git NOT executable: {git_exe}")
        else:
            notes.append(f"git executable OK ({git_exe})")
    except Exception as e:
        problems.append(f"git runnable check failed: {e}")

    # (3) baseline commit —— 没有它 watchdog 的 `git checkout HEAD --` 必然失败
    try:
        r = _subprocess.run(
            [git_exe, "-C", str(root), "rev-parse", "--verify", "HEAD"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=10,
        )
        if r.returncode == 0 and r.stdout.strip():
            notes.append("baseline commit OK")
        else:
            problems.append("no baseline commit (git rev-parse --verify HEAD failed)")
    except Exception as e:
        problems.append(f"baseline commit probe failed: {e}")

    # (4) watchdog 进程存活
    pid_path = root / ".pandaone" / ".watchdog_pid"
    if not pid_path.exists():
        problems.append("watchdog NOT running (no .watchdog_pid)")
    else:
        try:
            pid_text = pid_path.read_text(encoding="utf-8").strip()
        except Exception as e:
            pid_text = ""
            problems.append(f"watchdog pid file unreadable: {e}")
        if pid_text:
            try:
                from pandaone.cli import _pid_alive
                alive = bool(_pid_alive(pid_text))
            except Exception as e:
                alive = False
                problems.append(f"pid liveness probe failed: {e}")
            if alive:
                notes.append(f"watchdog alive (pid {pid_text})")
            else:
                problems.append(f"watchdog process NOT alive (pid {pid_text})")

    # (5) 冻结形态: 看门狗 exe 必须在 pandaone.exe 同级
    if getattr(_sys, "frozen", False):
        exe_dir = _Path(_sys.executable).resolve().parent
        guard = exe_dir / "pandaone_guard.exe"
        if guard.exists():
            notes.append("pandaone_guard.exe present")
        else:
            problems.append("pandaone_guard.exe MISSING next to pandaone.exe")

    if problems:
        return _layer(False, "; ".join(problems))
    return _layer(True, "; ".join(notes))


def _probe_install_hook_module():
    """在当前形态下真的把 install_hook 模块加载出来。

    返回 (module, source) —— module 为 None 表示加载不出来（= L3 FAIL）。

    为什么不是直接 `from pandaone.install_hook import ...`:
      冻结包的模块表（PYZ）里没有 pandaone.install_hook —— 它只作为"数据文件"
      被整棵树拷进 _internal/pandaone/，静态 import 直接 ImportError。
    为什么不是 `sys.executable -m pandaone.install_hook`:
      冻结形态下 sys.executable 就是 pandaone.exe 本身，没有 "-m 模块执行" 语义
      —— argparse 会把 "pandaone.install_hook" 当成子命令名，报
      "invalid choice: 'pandaone.install_hook'"（真机 0.7.32.0 实测到的真 bug）。

    所以走 cli_chunks/part_005.py 的 _load_install_hook_module（按路径加载）。
    注意: part_005.py 是给 cli.py exec 用的 chunk，自身没有 import sys / Path，
    单独 import 后调用会 NameError —— 此时回落到 pandaone.cli 里的同名函数
    （cli.py 把 chunk exec 进自己的 globals，sys/Path 都在里面）。
    两条路判定标准一致: 必须真的把 install_hook 模块加载出来。
    """
    attempts = []
    try:
        from pandaone.cli_chunks.part_005 import _load_install_hook_module as _fn
        attempts.append(("cli_chunks.part_005", _fn))
    except Exception:
        pass
    try:
        from pandaone.cli import _load_install_hook_module as _fn2
        attempts.append(("pandaone.cli", _fn2))
    except Exception:
        pass
    last_err = "no loader available"
    for source, fn in attempts:
        try:
            mod = fn()
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            continue
        if mod is not None:
            return mod, source
        last_err = "loader returned None"
    return None, last_err


def _check_layer3_pre_commit(root: _Path) -> dict:
    """v0.7.34.0: L3 真检 —— pre-commit hook 是不是**真的**装好且能拦人。

    之前只看 git 装没装 —— git 装了就算 OK，连 hook 文件在不在都不看。
    """
    if _git_executable() is None:
        return _na_layer("N/A - requires git (L3 pre-commit hook disabled)")

    # (a) hook 文件在不在
    hook_path = root / ".git" / "hooks" / "pre-commit"
    if not hook_path.exists():
        return _layer(False, f"hook NOT installed ({hook_path})")
    try:
        data = hook_path.read_bytes()
    except Exception as e:
        return _layer(False, f"hook unreadable: {e}")

    # (b) 归属校验 —— 判据同 install_hook.uninstall_hook（内容含 "Pandaone"）
    if "Pandaone" not in data.decode("utf-8", errors="ignore"):
        return _layer(False, "hook replaced (not ours) - no Pandaone marker")

    # (c) LF-only + 无 BOM —— 模板约定；Windows CRLF 会让 bash hook 完全失效
    if data.startswith(b"\xef\xbb\xbf"):
        return _layer(False, "hook has UTF-8 BOM (git cannot spawn it)")
    if b"\r\n" in data:
        return _layer(False, "hook has CRLF line endings (bash hook would fail)")

    # (d) pre-commit-check.py 存在且能被编译
    check_py = root / ".pandaone" / "pre-commit-check.py"
    if not check_py.exists():
        return _layer(False, f"pre-commit-check.py NOT installed ({check_py})")
    try:
        compile(check_py.read_text(encoding="utf-8"), str(check_py), "exec")
    except Exception as e:
        return _layer(False, f"pre-commit-check.py syntax error: {e}")

    # (e) 安装命令在当前形态可加载 —— 防 frozen 形态回归
    mod, source = _probe_install_hook_module()
    if mod is None:
        return _layer(False, f"install-hook module unloadable ({source})")

    # (f) config.json 的 protected_extensions 必须非空
    #     空的话 templates/pre-commit-check.py 匹配不到任何受保护文件 → 直接放行
    cfg_path = root / ".pandaone" / "config.json"
    if not cfg_path.exists():
        return _layer(False, "config.json NOT found (L3 has no baseline to enforce)")
    cfg, err = _read_json(cfg_path)
    if err:
        return _layer(False, f"config.json {err}")
    exts = (cfg or {}).get("protected_extensions") or []
    if not exts:
        return _layer(False, "config.json protected_extensions is EMPTY (hook would allow everything)")
    return _layer(
        True,
        f"hook installed, ours, LF-only, check script OK, install-hook loadable ({source})",
    )


def _check_layer4_startup(root: _Path) -> dict:
    """v0.7.34.0: L4 查对对象 —— 启动时自动加载的项目 README 摘要。

    之前 L4 查的是 `import watchdog`，但 watchdog 是 **L2** 的依赖（已挪过去）；
    L4 的真实机制是"每次启动自动加载项目 README 摘要"
    （cli_chunks/part_001.py 的 load_readme_summary，由 part_006.py 的 main 调用）。
    """
    readme = _find_readme(root)
    if readme is None:
        return _layer(False, "README NOT found in project root (startup summary unavailable)")
    try:
        readme.read_text(encoding="utf-8")
    except Exception as e:
        return _layer(False, f"README unreadable: {e}")
    try:
        from pandaone import cli as _cli
    except Exception as e:
        return _layer(False, f"cli import failed: {e}")
    try:
        orig = getattr(_cli, "README_PATH", None)
        try:
            # 摘要函数读的是模块级 README_PATH —— 临时指向项目 README
            _cli.README_PATH = readme
            summary = _cli.load_readme_summary()
        finally:
            if orig is None:
                try:
                    delattr(_cli, "README_PATH")
                except Exception:
                    pass
            else:
                _cli.README_PATH = orig
    except Exception as e:
        return _layer(False, f"readme summary loader raised: {type(e).__name__}: {e}")
    if not summary:
        return _layer(False, "readme summary empty")
    return _layer(True, f"README summary OK ({readme.name}, {len(summary)} lines)")


def _check_layer5_self_fingerprint(root: _Path) -> dict:
    """v0.7.34.0: L5 不误报 —— 先比 form，再比 hash。

    之前比对时**丢掉了 form 字段**直接比 hash → 同一台机器既装了 pip 版又装了
    exe 版时（合法部署行为），doctor 会误报 "TAMPERED"，用户会以为工具被篡改
    而不再信任 L5。

    同时: 无指纹文件从 "OK(首次运行)" 改成 **FAIL** —— 删掉指纹文件就能绕过
    自检，那不是"首次运行"，是基线缺失。

    存储格式解析走 fp_security.load_fp_record（兼容旧裸 hex + 新 json）。
    """
    try:
        from pandaone.cli import compute_fingerprint, FP_PATH
        from pandaone import fp_security as _fpsec
    except Exception as e:
        return _layer(False, f"fingerprint module import failed: {e}")
    if not FP_PATH.exists():
        return _layer(False, "no stored fingerprint (baseline missing)")
    try:
        rec = _fpsec.load_fp_record(path=FP_PATH)
    except Exception as e:
        return _layer(False, f"fingerprint file corrupted: {e}")
    try:
        current = compute_fingerprint()
    except Exception as e:
        return _layer(False, f"compute fingerprint failed: {e}")

    stored_form = rec.get("form") or _fpsec.FORM_SOURCE
    current_form = _fpsec.fp_form()
    if stored_form != current_form:
        # 形态切换是合法部署行为，不是篡改 —— 只 WARN，不报 TAMPERED
        return _layer(
            True,
            f"form switched (stored={stored_form}, current={current_form}) - baseline not comparable",
            warn=True,
        )

    stored_version = rec.get("version", "unknown")
    try:
        from pandaone.cli import _get_pandaone_version
        current_version = _get_pandaone_version()
    except Exception:
        current_version = None
    if current_version and stored_version and stored_version != current_version:
        # 版本变了 = 升级（CLI 自己的 check_fingerprint 也会 auto-refresh），不是篡改
        return _layer(
            True,
            f"version changed (stored=v{stored_version}, current=v{current_version}) - baseline not comparable",
            warn=True,
        )

    if rec.get("hash") == current:
        return _layer(True, f"matches stored fingerprint (v{stored_version}, form={current_form})")
    return _layer(False, f"TAMPERED (stored v{stored_version} != current SHA256)")


def _check_layer6_tamper_detection(root: _Path) -> dict:
    """v0.7.34.0: L6 三态计数 —— APPROVED / REJECTED / UNAUTHORIZED。

    之前只 count('"APPROVED"') / count('"REJECTED"')，**漏掉 UNAUTHORIZED**
    —— 而那才是 watchdog 抓到的真篡改（pandaone_guard/__main__.py 写的就是
    这个状态）。计数法照抄 cli_chunks/part_004.py cmd_status 的逐行 JSON 解析。
    """
    root_log = root / ".pandaone" / "pandaone.jsonl"
    root_cfg = root / ".pandaone" / "config.json"
    if root_log.exists():
        audit_log = root_log
    elif root_cfg.exists():
        # 项目已 init（config.json 在）却没有审计日志 = 审计基线被删
        return _layer(False, "audit log NOT found (audit baseline deleted)")
    else:
        # v0.7.24: 打包成 .exe 之后项目目录里没有 .pandaone/，回落到包目录的日志，
        #   只查包目录永远显示 "clean state"，会把真实信号掩盖掉。
        pkg_root = _Path(__file__).resolve().parent.parent.parent
        pkg_log = pkg_root / ".pandaone" / "pandaone.jsonl"
        if not pkg_log.exists():
            return _layer(True, "no audit log yet (clean state)")
        audit_log = pkg_log
    records = []
    try:
        for line in audit_log.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(_json.loads(line))
            except _json.JSONDecodeError:
                continue
    except Exception as e:
        return _layer(False, f"audit read failed: {e}")
    approved = sum(1 for r in records if r.get("status") == "APPROVED")
    rejected = sum(1 for r in records if r.get("status") == "REJECTED")
    unauthorized = sum(1 for r in records if r.get("status") == "UNAUTHORIZED")
    note = (
        f"audit log: {approved} APPROVED + {rejected} REJECTED "
        f"+ {unauthorized} UNAUTHORIZED"
    )
    if unauthorized > 0:
        return _layer(False, note + " (unauthorized tampering detected)")
    return _layer(True, note)


def _check_layer7_ci_audit() -> dict:
    """v0.7.19: 真查 .github/workflows/audit.yml + pull_request trigger (替代 L7 字面量)"""
    # v0.7.24: 打包成 .exe 之后没有 .github/workflows/audit.yml ——
    # CI 配置属于源码仓库，不进安装包。这里报 N/A 而不是 FAIL，
    # 否则 doctor 在打包态永远是红的，掩盖真正的问题。
    if getattr(_sys, "_MEIPASS", None):
        return _na_layer("not applicable (packaged build; CI workflow lives in the source repo)")
    # v0.7.19 fix: 用 __file__ 派生 repo root (不依赖 from pandaone.cli import ROOT, 避免 sys.modules cache 污染)
    # __file__ = src/pandaone/cmd_doctor.py, dirname 2 次上溯 = repo root
    repo_root = _Path(__file__).resolve().parent.parent.parent
    workflow = repo_root / ".github" / "workflows" / "audit.yml"
    if not workflow.exists():
        return _layer(False, f"{workflow} NOT found")
    try:
        text = workflow.read_text(encoding="utf-8")
    except Exception as e:
        return _layer(False, f"read failed: {e}")
    if "pull_request" in text or "pull-request" in text:
        return _layer(True, "audit.yml with pull_request trigger OK")
    return _layer(False, "audit.yml missing pull_request trigger")


def _check_layer8_path_conflict() -> dict:
    """v0.7.28.0: 检出 PATH 里**其它**的 pandaone 可执行文件。

    背景（真机实测，非推理）：Windows 的 PATH 拼接规则是
    「机器级 PATH + 用户级 PATH」，**机器级在前**。pip 版 pandaone 装在
    `Python\\Scripts\\`（常常在机器级 PATH 里），即使用户级 PATH 已经把
    exe 版的 `%LOCALAPPDATA%\\Pandaone` 前置到首位，敲 `pandaone` 命中的
    仍然是旧 pip 版 —— 用户体感就是"装了新版没生效"。

    委托给 `path_conflicts` 模块（doctor 与 setup 共用同一套判定）。
    只做**只读**探测：不执行任何外部 exe，只列出冲突路径。
    """
    try:
        from pandaone import path_conflicts as _pc
        return _pc.describe_conflicts()
    except Exception as e:  # 探测失败不该让 doctor 崩
        return _layer(True, f"path conflict check unavailable: {e}")


# ============================================================
# 2. 汇总
# ============================================================

def _collect_report(root=None):
    """收集所有诊断数据,返回 dict。

    v0.7.34.0:
      - 所有**项目级**检查都基于 root（不再绑死 cwd）
      - overall_ok 现在**吃层级失败**（排除显式标记 N/A 的层）
    """
    from pandaone.git_installer import (
        is_installed as _git_installed,
        version as _git_version,
        path as _git_path,
    )

    root = _resolve_root(root)

    if _git_installed():
        git_section = {"installed": True, "version": _git_version(), "path": _git_path()}
    else:
        git_section = {"installed": False, "version": None, "path": None}

    py_ver = _sys.version_info
    py_str = f"{py_ver.major}.{py_ver.minor}.{py_ver.micro}"
    py_section = {
        "version": py_str, "executable": _sys.executable, "required": ">=3.8",
        "ok": py_ver >= (3, 8), "too_old": py_ver < (3, 8),
    }

    try:
        from pandaone import __version__ as pver
    except Exception:
        pver = "unknown"
    # frozen (.exe): sys.executable 就是 pandaone.exe 本身。which("pandaone")
    # 指向的是 PATH 里的另一份（比如 site-packages 装的），会误导用户以为在查那个。
    _exe = (_sys.executable if getattr(_sys, "_MEIPASS", None)
            else _shutil.which("pandaone"))
    pandaone_section = {"version": pver, "executable": _exe}

    layers = {
        "L1_file_lock": _check_layer1_file_lock(root),
        "L2_watchdog_rollback": _check_layer2_watchdog(root),
        "L3_pre_commit_hook": _check_layer3_pre_commit(root),
        "L4_startup_check": _check_layer4_startup(root),
        "L5_self_fingerprint": _check_layer5_self_fingerprint(root),
        "L6_tamper_detection": _check_layer6_tamper_detection(root),
        "L7_ci_audit": _check_layer7_ci_audit(),
        "L8_path_conflict": _check_layer8_path_conflict(),
    }

    # N/A 的层不参与判定（显式标记，不是"沉默的通过"）
    applicable = {name: info for name, info in layers.items() if not info.get(_NA)}
    failed_layers = [name for name, info in applicable.items() if not info.get("ok")]
    layers_ok = not failed_layers

    return {
        "pandaone": pandaone_section, "python": py_section, "git": git_section,
        "root": str(root),
        "layers": layers,
        "failed_layers": failed_layers,
        "overall_ok": git_section["installed"] and py_section["ok"] and layers_ok,
    }


# ============================================================
# 3. 子命令
# ============================================================

def _ensure_i18n_extras():
    """注册 doctor 专用的 i18n key（i18n_extras 是显式注册，不自动 import）。"""
    try:
        from pandaone import i18n as _i18n
        from pandaone.i18n_extras import register_extras as _register
        _register(_i18n.TRANSLATIONS)
    except Exception:
        pass


def add_doctor_parser(sub_parsers_action):
    """把 doctor subparser 注册到给定的 subparsers action 上。"""
    doctor_p = sub_parsers_action.add_parser(
        "doctor",
        help="system health check (git / Python / 8-layer defenses)"
    )
    doctor_p.add_argument(
        "--root", default=_Path.cwd(),
        help="project root to check (default: current directory)"
    )
    doctor_p.add_argument(
        "--install-git", action="store_true",
        help="auto-install git if missing"
    )
    doctor_p.add_argument(
        "--clean-conflicts", action="store_true",
        help="rename older pandaone binaries that shadow the `pandaone` command"
    )
    doctor_p.add_argument(
        "--json", action="store_true",
        help="JSON output (machine-readable, for CI / MCP / IDE)"
    )


def cmd_doctor(args):
    """PR #28 — 系统健康检查 + 缺失依赖自动安装。

    v0.7.34.0 退出码语义:
      0 = 全部通过
      1 = 缺 git（既有语义不变）
      2 = Python 过旧（既有语义不变）
      3 = 有层级 FAIL（新增 —— 之前层失败也被当成"全部正常"）
    """
    _ensure_i18n_extras()
    try:
        from pandaone.i18n import t, init as _i18n_init
        _i18n_init(getattr(args, 'lang', None))
    except Exception:
        def t(k, **kw): return k

    want_install = getattr(args, 'install_git', False)
    want_json = getattr(args, 'json', False)
    # 注意：必须用 `is True` 严格判断 —— 调用方传 mock.Mock() 时，
    # 未显式设置的属性访问会返回 truthy 的 Mock 对象，`if getattr(...)` 会误入分支。
    want_clean = getattr(args, 'clean_conflicts', False) is True
    root = _resolve_root(getattr(args, 'root', None))

    if want_clean:
        # v0.7.28.0: 清理 PATH 里抢占命令的旧版 pandaone。
        #   放在 doctor 里是因为它本来就是"诊断 + 修复"工具（已有 --install-git 先例），
        #   安装器安装完直接调 `doctor --clean-conflicts`，不引入新子命令。
        try:
            from pandaone.cmd_setup import clean_path_conflicts as _clean
            status, msg = _clean()
            if want_json:
                print(_json.dumps({'step': 'clean_conflicts', 'status': status,
                                   'message': msg}, ensure_ascii=False))
            else:
                print(f'[{"OK" if status == "ok" else status.upper()}] {msg}')
        except Exception as e:
            if want_json:
                print(_json.dumps({'step': 'clean_conflicts', 'status': 'warn',
                                   'error': str(e)}, ensure_ascii=False))
            else:
                print(f'[WARN] {e}')
        report = _collect_report(root)
        if want_json:
            print(_json.dumps(report, ensure_ascii=False, indent=2))
        else:
            _print_human_report(report)
        return _exit_code(report)

    report = _collect_report(root)
    git_status = report['git']

    if want_install and not git_status['installed']:
        if want_json:
            print(_json.dumps({'step': 'install_git', 'status': 'starting'}, ensure_ascii=False))

        from pandaone.git_installer import install as _git_install, GitInstallError
        try:
            result = _git_install()
        except GitInstallError as e:
            if want_json:
                print(_json.dumps({
                    'step': 'install_git', 'status': 'failed', 'error': str(e),
                }, ensure_ascii=False))
            else:
                print(t('_doctor_git_install_failed'))
                print(str(e))
                from pandaone.git_installer import get_install_hint
                print(t('_doctor_manual_hint'))
                print(get_install_hint())
            return 1

        if want_json:
            print(_json.dumps({
                'step': 'install_git', 'status': 'ok',
                'channel': result.channel, 'version': result.version, 'path': result.path,
            }, ensure_ascii=False))
        else:
            print(t('_doctor_git_installed_via', channel=result.channel))
            print(t('_doctor_git_version', ver=result.version))
            print(t('_doctor_restart_shell_hint'))

        report = _collect_report(root)
        git_status = report['git']

    if want_json:
        print(_json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_human_report(report)

    return _exit_code(report)


def _exit_code(report) -> int:
    """退出码语义 —— 层级失败必须体现在退出码上（v0.7.34.0 核心修复）。"""
    if not report['git']['installed']:
        return 1
    if report['python']['too_old']:
        return 2
    if not report['overall_ok']:
        return 3
    return 0


def _print_human_report(report):
    """人类可读的报告"""
    _ensure_i18n_extras()
    from pandaone.i18n import t

    print(t('_doctor_title'))
    print('=' * 60)

    p = report['pandaone']
    print(f'  pandaone-guard : {p["version"]}')
    if p['executable']:
        print(f'    executable  : {p["executable"]}')
    if report.get('root'):
        print(f'    root        : {report["root"]}')

    py = report['python']
    py_status = 'OK' if py['ok'] else '[FAIL]'
    print(f'  [{py_status}] Python {py["version"]}  (required {py["required"]})')

    g = report['git']
    if g['installed']:
        print(f'  [OK]   Git {g["version"]}')
        print(f'          path: {g["path"]}')
    else:
        print('  [FAIL] Git NOT installed')
        print('          L2 (watchdog rollback) and L3 (pre-commit hook) will be DISABLED')

    print()
    print(t('_doctor_layer_header'))
    for layer_name, layer_info in report['layers'].items():
        if layer_info.get(_NA):
            status = '[N/A] '
        elif not layer_info.get('ok'):
            status = '[FAIL]'
        elif layer_info.get(_WARN):
            status = '[WARN]'
        else:
            status = '[OK]  '
        print(f'  {status} {layer_name:30s} : {layer_info["note"]}')

    print()
    if report['overall_ok']:
        print(t('_doctor_all_ok'))
    else:
        print(t('_doctor_action_needed'))
        failed = report.get('failed_layers')
        if failed is None:
            failed = [
                name for name, info in report['layers'].items()
                if not info.get(_NA) and not info.get('ok')
            ]
        for name in failed:
            print(f'  -> {name}: {report["layers"][name]["note"]}')
        if not g['installed']:
            print(t('_doctor_run_install_git'))
        if py['too_old']:
            print(t('_doctor_upgrade_python', required=py['required']))

    # L8: PATH 冲突 —— 装完新版却仍命中旧版时，这里会直接点名路径
    l8 = report['layers'].get('L8_path_conflict') or {}
    for p in (l8.get('shadow') or []):
        print(t('_doctor_path_conflict', path=p))
        print(t('_doctor_path_conflict_hint'))
