# -*- coding: utf-8 -*-
"""
test_cmd_doctor_layers.py — `pandaone doctor` 各层"真检"能力回归测试 (v0.7.34.0)

为什么必须有这个文件
--------------------
tests/test_cmd_doctor.py 之前**只断言 7 个层名存在**，没有任何一条测试断言
"某层能判 FAIL" —— 这正是"存在性体检"缺陷能长期存活的根本原因：
L1 是无条件 True 的字面量、L2/L3 只看 git 装没装、L4 查错了对象（import watchdog），
但没有任何测试会发现这些。

本文件补上这一层：每一层都要有"构造出坏状态 → 该层必须 FAIL"的用例，
外加 P0 守门测试（层失败 → overall_ok False **且** 退出码非 0）。

覆盖:
  P0 守门   层失败 → overall_ok False 且退出码非 0；N/A 层不参与判定
  P1 L3     hook 没装 / 被替换成空壳 / CRLF / 缺 pre-commit-check.py /
            protected_extensions 为空 → 全部 FAIL
  P2 L2     没有 baseline commit 的 git 仓库 → FAIL
  P3 L1     受保护文件可写 → FAIL
  P4 L6     审计日志含 UNAUTHORIZED → FAIL；REJECTED 仍算 OK 但要显示数量
  P5 L4     缺 README → FAIL
  P6 L5     form 不同时**不**报 TAMPERED；无指纹文件 → FAIL
"""
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from pandaone import cmd_doctor as _doc  # noqa: E402

LAYER_NAMES = [
    "L1_file_lock", "L2_watchdog_rollback", "L3_pre_commit_hook",
    "L4_startup_check", "L5_self_fingerprint", "L6_tamper_detection",
    "L7_ci_audit", "L8_path_conflict",
]

#: 一个"健康"的 hook（内容含 Pandaone 标识 + LF 换行）
GOOD_HOOK = "#!/bin/sh\n# Pandaone AI Agent pre-commit hook\nexit 0\n"


# ============================================================
# 辅助
# ============================================================

def _git_exe():
    from pandaone.git_installer import _find_git_executable
    return _find_git_executable()


def _project(tmp_path, *, hook=GOOD_HOOK, protected_extensions=None,
             check_script=True, config=True, readme=True, audit=None):
    """搭一个最小项目骨架，返回项目根目录。"""
    (tmp_path / ".git" / "hooks").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".pandaone").mkdir(parents=True, exist_ok=True)
    if hook is not None:
        (tmp_path / ".git" / "hooks" / "pre-commit").write_bytes(hook.encode("utf-8"))
    if check_script:
        (tmp_path / ".pandaone" / "pre-commit-check.py").write_text(
            "print('ok')\n", encoding="utf-8")
    if config:
        exts = [".py"] if protected_extensions is None else protected_extensions
        cfg = {"protected_extensions": exts, "exclude_patterns": []}
        (tmp_path / ".pandaone" / "config.json").write_text(
            json.dumps(cfg), encoding="utf-8")
    if audit is not None:
        (tmp_path / ".pandaone" / "pandaone.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in audit) + "\n",
            encoding="utf-8")
    if readme:
        (tmp_path / "README.md").write_text(
            "# demo\n\n## 当前阶段\n\n**Phase 1** demo\n", encoding="utf-8")
    (tmp_path / "demo.py").write_text("print('demo')\n", encoding="utf-8")
    return tmp_path


def _assert_real_failure(info):
    """断言这是一次**真的**失败（N/A 不算失败 —— 那会掩盖问题）。"""
    assert not info.get("na"), f"layer was N/A, expected a real failure: {info['note']}"
    assert info["ok"] is False, f"expected FAIL, got {info}"


def _args(root, json_out=False):
    return SimpleNamespace(root=str(root), json=json_out, install_git=False,
                           clean_conflicts=False, lang="en")


# ============================================================
# P0 — 汇总层必须吃层级失败（最重要）
# ============================================================

class TestP0SummaryGate:
    def test_layer_failure_makes_overall_ok_false(self, tmp_path):
        p = _project(tmp_path, hook=None)          # hook 没装 → L3 必 FAIL
        report = _doc._collect_report(p)
        assert report["layers"]["L3_pre_commit_hook"]["ok"] is False
        assert "L3_pre_commit_hook" in report["failed_layers"]
        assert report["overall_ok"] is False

    def test_layer_failure_makes_exit_code_nonzero(self, tmp_path, capsys):
        p = _project(tmp_path, hook=None)          # hook 没装 → L3 必 FAIL
        rc = _doc.cmd_doctor(_args(p, json_out=True))
        capsys.readouterr()
        assert rc != 0, "层失败时退出码必须非 0（P0 核心修复）"
        assert rc == 3, f"层失败应返回 3，实际 {rc}"

    def test_exit_code_3_not_confused_with_git_or_python_codes(self, tmp_path, capsys):
        """1 = 缺 git，2 = Python 过旧，3 = 层失败 —— 三者不能混。"""
        p = _project(tmp_path, hook=None)
        rc = _doc.cmd_doctor(_args(p, json_out=True))
        capsys.readouterr()
        assert rc not in (1, 2)

    def test_human_report_does_not_claim_all_ok(self, tmp_path, capsys):
        from pandaone.i18n import t
        p = _project(tmp_path, hook=None)
        _doc.cmd_doctor(_args(p))
        out = capsys.readouterr().out
        assert "L3_pre_commit_hook" in out
        assert t("_doctor_all_ok") not in out, "层失败时不能打印\"全部正常\"横幅"

    def test_na_layers_are_excluded_from_overall_ok(self, tmp_path, monkeypatch):
        """显式 N/A 的层不参与判定（否则打包态 doctor 永远是红的）。"""
        for name in ("_check_layer1_file_lock", "_check_layer2_watchdog",
                     "_check_layer3_pre_commit", "_check_layer4_startup",
                     "_check_layer5_self_fingerprint", "_check_layer6_tamper_detection",
                     "_check_layer7_ci_audit", "_check_layer8_path_conflict"):
            monkeypatch.setattr(_doc, name, lambda root=None: _doc._layer(True, "stub"))
        monkeypatch.setattr(_doc, "_check_layer2_watchdog",
                            lambda root=None: _doc._na_layer("N/A - test"))
        report = _doc._collect_report(tmp_path)
        assert report["failed_layers"] == []
        assert report["overall_ok"] is True

    def test_failed_layer_is_listed_in_report(self, tmp_path, monkeypatch):
        for name in ("_check_layer1_file_lock", "_check_layer2_watchdog",
                     "_check_layer4_startup", "_check_layer5_self_fingerprint",
                     "_check_layer6_tamper_detection", "_check_layer7_ci_audit",
                     "_check_layer8_path_conflict"):
            monkeypatch.setattr(_doc, name, lambda root=None: _doc._layer(True, "stub"))
        monkeypatch.setattr(_doc, "_check_layer3_pre_commit",
                            lambda root=None: _doc._layer(False, "stub failure"))
        report = _doc._collect_report(tmp_path)
        assert report["failed_layers"] == ["L3_pre_commit_hook"]
        assert report["overall_ok"] is False

    def test_report_has_all_eight_layers(self, tmp_path):
        report = _doc._collect_report(tmp_path)
        for name in LAYER_NAMES:
            assert name in report["layers"]
            assert "ok" in report["layers"][name]
            assert "note" in report["layers"][name]


# ============================================================
# P1 — L3 pre-commit hook 真检
# ============================================================

class TestLayer3PreCommit:
    def test_l3_fails_when_hook_not_installed(self, tmp_path):
        p = _project(tmp_path, hook=None)
        info = _doc._check_layer3_pre_commit(p)
        _assert_real_failure(info)
        assert "NOT installed" in info["note"]

    def test_l3_fails_when_hook_replaced_by_empty_shell(self, tmp_path):
        """hook 被换成 `exit 0` 空壳 —— 审计门禁形同虚设，必须判 FAIL。"""
        p = _project(tmp_path, hook="#!/bin/sh\nexit 0\n")
        info = _doc._check_layer3_pre_commit(p)
        _assert_real_failure(info)
        assert "not ours" in info["note"]

    def test_l3_fails_when_hook_has_crlf(self, tmp_path):
        """Windows CRLF 会让 bash hook 完全失效。"""
        p = _project(tmp_path, hook="#!/bin/sh\r\n# Pandaone\r\nexit 0\r\n")
        info = _doc._check_layer3_pre_commit(p)
        _assert_real_failure(info)
        assert "CRLF" in info["note"]

    def test_l3_fails_when_hook_has_bom(self, tmp_path):
        p = _project(tmp_path, hook="\ufeff#!/bin/sh\n# Pandaone\nexit 0\n")
        info = _doc._check_layer3_pre_commit(p)
        _assert_real_failure(info)
        assert "BOM" in info["note"]

    def test_l3_fails_when_check_script_missing(self, tmp_path):
        p = _project(tmp_path, check_script=False)
        info = _doc._check_layer3_pre_commit(p)
        _assert_real_failure(info)
        assert "pre-commit-check.py" in info["note"]

    def test_l3_fails_when_check_script_has_syntax_error(self, tmp_path):
        p = _project(tmp_path)
        (p / ".pandaone" / "pre-commit-check.py").write_text(
            "def broken(:\n", encoding="utf-8")
        info = _doc._check_layer3_pre_commit(p)
        _assert_real_failure(info)
        assert "syntax error" in info["note"]

    def test_l3_fails_when_protected_extensions_empty(self, tmp_path):
        """protected_extensions 为空 → pre-commit-check.py 匹配不到任何文件 → 放行一切。"""
        p = _project(tmp_path, protected_extensions=[])
        info = _doc._check_layer3_pre_commit(p)
        _assert_real_failure(info)
        assert "EMPTY" in info["note"]

    def test_l3_fails_when_config_missing(self, tmp_path):
        p = _project(tmp_path, config=False)
        info = _doc._check_layer3_pre_commit(p)
        _assert_real_failure(info)
        assert "config.json" in info["note"]

    def test_l3_ok_for_healthy_project(self, tmp_path):
        p = _project(tmp_path)
        info = _doc._check_layer3_pre_commit(p)
        assert info.get("na") is not True
        assert info["ok"] is True, info["note"]
        assert "install-hook loadable" in info["note"]

    def test_l3_is_na_when_git_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_doc, "_git_executable", lambda: None)
        info = _doc._check_layer3_pre_commit(tmp_path)
        assert info.get("na") is True


# ============================================================
# P2 — L2 watchdog 回滚真检
# ============================================================

class TestLayer2Watchdog:
    def test_l2_fails_without_baseline_commit(self, tmp_path):
        """git 仓库但没有 baseline commit —— watchdog 的 git checkout 回滚必然失败。"""
        p = _project(tmp_path)
        git = _git_exe()
        assert git, "git 不可用（conftest 应已保证）"
        r = subprocess.run([git, "init", "-q", str(p)],
                           capture_output=True, timeout=60)
        assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
        info = _doc._check_layer2_watchdog(p)
        _assert_real_failure(info)
        assert "baseline commit" in info["note"]

    def test_l2_fails_when_watchdog_not_running(self, tmp_path):
        p = _project(tmp_path)
        info = _doc._check_layer2_watchdog(p)
        _assert_real_failure(info)
        assert "watchdog" in info["note"]

    def test_l2_is_na_when_git_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_doc, "_git_executable", lambda: None)
        info = _doc._check_layer2_watchdog(tmp_path)
        assert info.get("na") is True


# ============================================================
# P3 — L1 文件锁真检
# ============================================================

class TestLayer1FileLock:
    def test_l1_fails_when_protected_files_writable(self, tmp_path):
        p = _project(tmp_path)
        info = _doc._check_layer1_file_lock(p)
        _assert_real_failure(info)
        assert "writable" in info["note"]

    def test_l1_ok_when_protected_files_locked(self, tmp_path):
        import os
        import stat as _stat
        p = _project(tmp_path)
        for f in p.rglob("*.py"):
            os.chmod(f, _stat.S_IREAD)
        try:
            info = _doc._check_layer1_file_lock(p)
            assert info["ok"] is True, info["note"]
            assert "locked" in info["note"]
        finally:
            for f in p.rglob("*.py"):
                try:
                    os.chmod(f, _stat.S_IREAD | _stat.S_IWRITE)
                except OSError:
                    pass


# ============================================================
# P4 — L6 三态计数
# ============================================================

class TestLayer6TamperDetection:
    def test_l6_fails_when_unauthorized_record_present(self, tmp_path):
        """UNAUTHORIZED 才是 watchdog 抓到的真篡改 —— 必须判 FAIL。"""
        p = _project(tmp_path, audit=[
            {"id": "audit_1", "status": "APPROVED", "file": "demo.py"},
            {"id": "audit_2", "status": "UNAUTHORIZED", "file": "demo.py"},
        ])
        info = _doc._check_layer6_tamper_detection(p)
        _assert_real_failure(info)
        assert "UNAUTHORIZED" in info["note"]

    def test_l6_counts_approved_rejected_unauthorized(self, tmp_path):
        p = _project(tmp_path, audit=[
            {"id": "audit_1", "status": "APPROVED", "file": "demo.py"},
            {"id": "audit_2", "status": "REJECTED", "file": "demo.py"},
            {"id": "audit_3", "status": "APPROVED", "file": "demo.py"},
        ])
        info = _doc._check_layer6_tamper_detection(p)
        assert info["ok"] is True
        assert "2 APPROVED" in info["note"]
        assert "1 REJECTED" in info["note"]
        assert "0 UNAUTHORIZED" in info["note"]

    def test_l6_fails_when_audit_baseline_deleted(self, tmp_path):
        """config.json 在（项目已 init）但审计日志没了 = 基线被删。"""
        p = _project(tmp_path)
        info = _doc._check_layer6_tamper_detection(p)
        _assert_real_failure(info)
        assert "audit log" in info["note"]

    def test_l6_ok_on_first_run_without_config(self, tmp_path, monkeypatch):
        """没 init 过（无 config.json）+ 无审计日志 → 首次运行，保持 OK。"""
        p = _project(tmp_path, config=False)
        # 把包目录基准指到临时项目，避免命中源码仓的审计日志（结果依赖机器状态）
        monkeypatch.setattr(_doc, "__file__", str(p / "pkg" / "x" / "cmd_doctor.py"))
        info = _doc._check_layer6_tamper_detection(p)
        assert info["ok"] is True
        assert "no audit log" in info["note"]


# ============================================================
# P5 — L4 启动自检查对对象
# ============================================================

class TestLayer4Startup:
    def test_l4_fails_when_readme_missing(self, tmp_path):
        p = _project(tmp_path, readme=False)
        info = _doc._check_layer4_startup(p)
        _assert_real_failure(info)
        assert "README" in info["note"]

    def test_l4_ok_with_readme(self, tmp_path):
        p = _project(tmp_path)
        info = _doc._check_layer4_startup(p)
        assert info["ok"] is True, info["note"]
        assert "README summary OK" in info["note"]


# ============================================================
# P6 — L5 自指纹不误报
# ============================================================

class TestLayer5SelfFingerprint:
    def _write_fp(self, tmp_path, monkeypatch, *, form, version, digest):
        from pandaone import cli as _cli
        fp = tmp_path / "fp.txt"
        fp.write_text(json.dumps({
            "version": version, "hash": digest, "form": form,
            "stored_at": "2026-01-01T00:00:00Z",
        }), encoding="utf-8")
        monkeypatch.setattr(_cli, "FP_PATH", fp)

    def test_form_mismatch_does_not_report_tampered(self, tmp_path, monkeypatch):
        """同一台机器既装 pip 版又装 exe 版是合法部署行为，不能报 TAMPERED。"""
        from pandaone import fp_security as _fpsec
        self._write_fp(tmp_path, monkeypatch, form="source",
                       version="0.7.33.0", digest="deadbeef")
        monkeypatch.setattr(_fpsec, "fp_form", lambda: "frozen")
        info = _doc._check_layer5_self_fingerprint(tmp_path)
        assert info["ok"] is True, info["note"]
        assert info.get("warn") is True
        assert "TAMPERED" not in info["note"]
        assert "form switched" in info["note"]

    def test_same_form_hash_mismatch_is_tampered(self, tmp_path, monkeypatch):
        from pandaone import cli as _cli
        from pandaone import fp_security as _fpsec
        version = _cli._get_pandaone_version()
        self._write_fp(tmp_path, monkeypatch, form="source",
                       version=version, digest="deadbeef")
        monkeypatch.setattr(_fpsec, "fp_form", lambda: "source")
        info = _doc._check_layer5_self_fingerprint(tmp_path)
        _assert_real_failure(info)
        assert "TAMPERED" in info["note"]

    def test_missing_fingerprint_file_is_failure(self, tmp_path, monkeypatch):
        """删掉指纹文件绕过自检 —— 不是"首次运行"，是基线缺失。"""
        from pandaone import cli as _cli
        monkeypatch.setattr(_cli, "FP_PATH", tmp_path / "absent_fp.txt")
        info = _doc._check_layer5_self_fingerprint(tmp_path)
        _assert_real_failure(info)
        assert "baseline missing" in info["note"]


# ============================================================
# --root 参数
# ============================================================

class TestDoctorRootOption:
    def test_parser_accepts_root(self):
        import argparse
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        _doc.add_doctor_parser(sub)
        args = sub.choices["doctor"].parse_args(["--root", "/tmp/demo"])
        assert Path(args.root) == Path("/tmp/demo")

    def test_parser_root_defaults_to_cwd(self):
        import argparse
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        _doc.add_doctor_parser(sub)
        args = sub.choices["doctor"].parse_args([])
        assert Path(args.root) == Path.cwd()

    def test_report_root_follows_argument(self, tmp_path):
        p = _project(tmp_path)
        report = _doc._collect_report(p)
        assert Path(report["root"]) == p.resolve()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
