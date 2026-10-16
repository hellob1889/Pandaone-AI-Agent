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
    A: Python dict 引用语义保证。cli.COMMANDS["doctor"] = cmd_doctor
       修改的是同一个 dict 对象。cli.main() 调 COMMANDS.get(args.command)
       能看到 doctor。
"""
from __future__ import annotations

import json as _json
import shutil as _shutil
import sys as _sys


def _check_layer4_startup() -> dict:
    """v0.7.19: 真查 watchdog 是否可 import (替代 L4 字面量 'OK')"""
    try:
        import watchdog  # noqa: F401
        return {"ok": True, "note": "watchdog importable"}
    except ImportError:
        return {"ok": False, "note": "watchdog NOT installed (L4 disabled)"}


def _check_layer5_self_fingerprint() -> dict:
    """v0.7.19: 真算 pandaone.py SHA256 vs 存储 fingerprint (替代 L5 字面量 'OK')"""
    try:
        from pandaone.cli import compute_fingerprint, FP_PATH
    except ImportError as e:
        return {"ok": False, "note": f"pandaone.cli import failed: {e}"}
    try:
        current = compute_fingerprint()
    except Exception as e:
        return {"ok": False, "note": f"compute fingerprint failed: {e}"}
    if not FP_PATH.exists():
        return {"ok": True, "note": "no stored fingerprint (first run)"}
    try:
        stored = FP_PATH.read_text(encoding="utf-8").strip()
    except Exception as e:
        return {"ok": False, "note": f"read fingerprint failed: {e}"}
    if stored == current:
        return {"ok": True, "note": "matches stored fingerprint"}
    return {"ok": False, "note": "TAMPERED (stored != current SHA256)"}


def _check_layer6_tamper_detection() -> dict:
    """v0.7.19: 真查 .pandaone/pandaone.jsonl audit log 状态 (替代 L6 字面量 'OK')"""
    audit_log = _Path.home() / ".pandaone" / "pandaone.jsonl"
    if not audit_log.exists():
        return {"ok": True, "note": "no audit log yet (clean state)"}
    try:
        text = audit_log.read_text(encoding="utf-8")
        approved = text.count('"APPROVED"')
        rejected = text.count('"REJECTED"')
        return {
            "ok": True,
            "note": f"audit log: {approved} APPROVED + {rejected} REJECTED",
        }
    except Exception as e:
        return {"ok": False, "note": f"audit read failed: {e}"}


def _check_layer7_ci_audit() -> dict:
    """v0.7.19: 真查 .github/workflows/audit.yml + pull_request trigger (替代 L7 字面量)"""
    try:
        from pandaone.cli import ROOT
    except ImportError as e:
        return {"ok": False, "note": f"pandaone.cli import failed: {e}"}
    workflow = ROOT / ".github" / "workflows" / "audit.yml"
    if not workflow.exists():
        return {"ok": False, "note": f"{workflow} NOT found"}
    try:
        text = workflow.read_text(encoding="utf-8")
    except Exception as e:
        return {"ok": False, "note": f"read failed: {e}"}
    if "pull_request" in text or "pull-request" in text:
        return {"ok": True, "note": "audit.yml with pull_request trigger OK"}
    return {"ok": False, "note": "audit.yml missing pull_request trigger"}


def _check_layer5_self_fingerprint() -> dict:
    """v0.7.19: 真算 pandaone.py SHA256 vs 存储 fingerprint (替代 L5 字面量 'OK')"""
    try:
        from pandaone.cli import compute_fingerprint, FP_PATH
    except ImportError as e:
        return {"ok": False, "note": f"pandaone.cli import failed: {e}"}
    try:
        current = compute_fingerprint()
    except Exception as e:
        return {"ok": False, "note": f"compute fingerprint failed: {e}"}
    if not FP_PATH.exists():
        return {"ok": True, "note": "no stored fingerprint (first run)"}
    try:
        stored = FP_PATH.read_text(encoding="utf-8").strip()
    except Exception as e:
        return {"ok": False, "note": f"read fingerprint failed: {e}"}
    if stored == current:
        return {"ok": True, "note": "matches stored fingerprint"}
    return {"ok": False, "note": "TAMPERED (stored != current SHA256)"}


def _check_layer6_tamper_detection() -> dict:
    """v0.7.19: 真查 .pandaone/pandaone.jsonl audit log 状态 (替代 L6 字面量 'OK')"""
    audit_log = _Path.home() / ".pandaone" / "pandaone.jsonl"
    if not audit_log.exists():
        return {"ok": True, "note": "no audit log yet (clean state)"}
    try:
        text = audit_log.read_text(encoding="utf-8")
        approved = text.count('"APPROVED"')
        rejected = text.count('"REJECTED"')
        return {
            "ok": True,
            "note": f"audit log: {approved} APPROVED + {rejected} REJECTED",
        }
    except Exception as e:
        return {"ok": False, "note": f"audit read failed: {e}"}


def _check_layer7_ci_audit() -> dict:
    """v0.7.19: 真查 .github/workflows/audit.yml + pull_request trigger (替代 L7 字面量)"""
    try:
        from pandaone.cli import ROOT
    except ImportError as e:
        return {"ok": False, "note": f"pandaone.cli import failed: {e}"}
    workflow = ROOT / ".github" / "workflows" / "audit.yml"
    if not workflow.exists():
        return {"ok": False, "note": f"{workflow} NOT found"}
    try:
        text = workflow.read_text(encoding="utf-8")
    except Exception as e:
        return {"ok": False, "note": f"read failed: {e}"}
    if "pull_request" in text or "pull-request" in text:
        return {"ok": True, "note": "audit.yml with pull_request trigger OK"}
    return {"ok": False, "note": "audit.yml missing pull_request trigger"}



def add_doctor_parser(sub_parsers_action):
    """把 doctor subparser 注册到给定的 subparsers action 上。"""
    doctor_p = sub_parsers_action.add_parser(
        "doctor",
        help="system health check (git / Python / 7-layer defenses)"
    )
    doctor_p.add_argument(
        "--install-git", action="store_true",
        help="auto-install git if missing"
    )
    doctor_p.add_argument(
        "--json", action="store_true",
        help="JSON output (machine-readable, for CI / MCP / IDE)"
    )


def cmd_doctor(args):
    """PR #28 — 系统健康检查 + 缺失依赖自动安装。"""
    try:
        from pandaone.i18n import t, init as _i18n_init
        _i18n_init(getattr(args, "lang", None))
    except Exception:
        def t(k, **kw): return k

    want_install = getattr(args, "install_git", False)
    want_json = getattr(args, "json", False)

    report = _collect_report()
    git_status = report["git"]

    if want_install and not git_status["installed"]:
        if want_json:
            print(_json.dumps({"step": "install_git", "status": "starting"}, ensure_ascii=False))

        from pandaone.git_installer import install as _git_install, GitInstallError
        try:
            result = _git_install()
        except GitInstallError as e:
            if want_json:
                print(_json.dumps({
                    "step": "install_git", "status": "failed", "error": str(e),
                }, ensure_ascii=False))
            else:
                print(t("_doctor_git_install_failed"))
                print(str(e))
                from pandaone.git_installer import get_install_hint
                print(t("_doctor_manual_hint"))
                print(get_install_hint())
            return 1

        if want_json:
            print(_json.dumps({
                "step": "install_git", "status": "ok",
                "channel": result.channel, "version": result.version, "path": result.path,
            }, ensure_ascii=False))
        else:
            print(t("_doctor_git_installed_via", channel=result.channel))
            print(t("_doctor_git_version", ver=result.version))
            print(t("_doctor_restart_shell_hint"))

        report = _collect_report()
        git_status = report["git"]

    if want_json:
        print(_json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_human_report(report)

    if not git_status["installed"]:
        return 1
    if report["python"]["too_old"]:
        return 2
    return 0


def _collect_report():
    """收集所有诊断数据,返回 dict"""
    from pandaone.git_installer import (
        is_installed as _git_installed,
        version as _git_version,
        path as _git_path,
    )

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
    pandaone_section = {"version": pver, "executable": _shutil.which("pandaone")}

    layers = {
        "L1_file_lock": {"ok": True, "note": "python-only (attrib/chmod)"},
        "L2_watchdog_rollback": {
            "ok": git_section["installed"],
            "note": "OK" if git_section["installed"] else "DISABLED - requires git",
        },
        "L3_pre_commit_hook": {
            "ok": git_section["installed"],
            "note": "OK" if git_section["installed"] else "DISABLED - requires git",
        },
        "L4_startup_check": _check_layer4_startup(),
        "L5_self_fingerprint": _check_layer5_self_fingerprint(),
        "L6_tamper_detection": _check_layer6_tamper_detection(),
        "L7_ci_audit": _check_layer7_ci_audit(),
    }

    return {
        "pandaone": pandaone_section, "python": py_section, "git": git_section,
        "layers": layers, "overall_ok": git_section["installed"] and py_section["ok"],
    }


def _print_human_report(report):
    """人类可读的报告"""
    from pandaone.i18n import t

    print(t("_doctor_title"))
    print("=" * 60)

    p = report["pandaone"]
    print(f"  pandaone-guard : {p['version']}")
    if p["executable"]:
        print(f"    executable  : {p['executable']}")

    py = report["python"]
    py_status = "OK" if py["ok"] else "[FAIL]"
    print(f"  [{py_status}] Python {py['version']}  (required {py['required']})")

    g = report["git"]
    if g["installed"]:
        print(f"  [OK]   Git {g['version']}")
        print(f"          path: {g['path']}")
    else:
        print(f"  [FAIL] Git NOT installed")
        print(f"          L2 (watchdog rollback) and L3 (pre-commit hook) will be DISABLED")

    print()
    print(t("_doctor_layer_header"))
    for layer_name, layer_info in report["layers"].items():
        status = "[OK]  " if layer_info["ok"] else "[FAIL]"
        print(f"  {status} {layer_name:30s} : {layer_info['note']}")

    print()
    if report["overall_ok"]:
        print(t("_doctor_all_ok"))
    else:
        print(t("_doctor_action_needed"))
        if not g["installed"]:
            print(t("_doctor_run_install_git"))
        if py["too_old"]:
            print(t("_doctor_upgrade_python", required=py["required"]))
