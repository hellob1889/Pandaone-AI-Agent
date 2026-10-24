# -*- coding: utf-8 -*-
"""
test_cmd_doctor.py — PR #28 cmd_doctor 模块单元测试
"""
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# v0.7.19 hotfix: 改用 module 引用, 让 mock.patch("pandaone.cmd_doctor._collect_report") work
# (旧 from-import 是值引用, mock patch module attr 不影响 test 用的引用)
from pandaone import cmd_doctor as _cmd_doc_mod  # v0.7.19 hotfix 2: mock.patch.object uses this
cmd_doctor = _cmd_doc_mod.cmd_doctor
add_doctor_parser = _cmd_doc_mod.add_doctor_parser
_collect_report = _cmd_doc_mod._collect_report
_print_human_report = _cmd_doc_mod._print_human_report


class TestAddDoctorParser:
    def test_adds_doctor_to_subparsers(self):
        import argparse
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        add_doctor_parser(sub)
        assert "doctor" in sub.choices
        args = sub.choices["doctor"].parse_args([])
        assert isinstance(args, argparse.Namespace)
        assert hasattr(args, "install_git")
        assert hasattr(args, "json")

    def test_accepts_install_git_flag(self):
        import argparse
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        add_doctor_parser(sub)
        args = sub.choices["doctor"].parse_args(["--install-git"])
        assert args.install_git is True

    def test_accepts_json_flag(self):
        import argparse
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        add_doctor_parser(sub)
        args = sub.choices["doctor"].parse_args(["--json"])
        assert args.json is True

    def test_accepts_clean_conflicts_flag(self):
        import argparse
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        add_doctor_parser(sub)
        args = sub.choices["doctor"].parse_args(["--clean-conflicts"])
        assert args.clean_conflicts is True

    def test_clean_conflicts_defaults_false(self):
        import argparse
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        add_doctor_parser(sub)
        args = sub.choices["doctor"].parse_args([])
        assert args.clean_conflicts is False


class TestCollectReport:
    def test_report_has_all_keys(self):
        report = _collect_report()
        for k in ["pandaone", "python", "git", "layers", "overall_ok"]:
            assert k in report

    def test_python_section_fields(self):
        py = _collect_report()["python"]
        for k in ["version", "executable", "required", "ok", "too_old"]:
            assert k in py

    def test_git_section_fields(self):
        g = _collect_report()["git"]
        for k in ["installed", "version", "path"]:
            assert k in g

    def test_layers_has_all_7(self):
        layers = _collect_report()["layers"]
        for name in ["L1_file_lock", "L2_watchdog_rollback", "L3_pre_commit_hook",
                     "L4_startup_check", "L5_self_fingerprint", "L6_tamper_detection",
                     "L7_ci_audit"]:
            assert name in layers

    def test_layer_format(self):
        layers = _collect_report()["layers"]
        for name, info in layers.items():
            assert "ok" in info and "note" in info

    def test_overall_ok_logic(self):
        report = _collect_report()
        expected = report["git"]["installed"] and report["python"]["ok"]
        assert report["overall_ok"] == expected


def _make_args(install_git=False, json_out=False, lang="en", clean_conflicts=False):
    args = mock.Mock()
    args.install_git = install_git
    args.json = json_out
    args.lang = lang
    # 必须显式设置：mock.Mock() 未显式设置的属性访问返回 truthy 的 Mock 对象
    args.clean_conflicts = clean_conflicts
    return args


def _ok_report():
    return {
        "git": {"installed": True, "version": "git version 2.43.0", "path": "/usr/bin/git"},
        "python": {"version": "3.10", "executable": "/usr/bin/python", "required": ">=3.8",
                   "ok": True, "too_old": False},
        "pandaone": {"version": "0.7.7", "executable": "/usr/bin/pandaone"},
        "layers": {},
        "overall_ok": True,
    }


class TestCmdDoctorJSON:
    def test_json_output(self, capsys):
        with mock.patch.object(_cmd_doc_mod, "_collect_report", return_value=_ok_report()):
            exit_code = cmd_doctor(_make_args(json_out=True))
            captured = capsys.readouterr()
        out = captured.out
        start = out.find("{")
        assert start >= 0
        depth = 0
        end = start
        for i in range(start, len(out)):
            if out[i] == "{":
                depth += 1
            elif out[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        report = json.loads(out[start:end])
        for k in ["pandaone", "python", "git"]:
            assert k in report

    def test_exit_code_zero_when_all_ok(self):
        with mock.patch.object(_cmd_doc_mod, "_collect_report", return_value=_ok_report()):
            assert cmd_doctor(_make_args(json_out=True)) == 0

    def test_exit_code_one_when_git_missing(self):
        report = _ok_report()
        report["git"]["installed"] = False
        report["git"]["version"] = None
        report["git"]["path"] = None
        report["overall_ok"] = False
        with mock.patch.object(_cmd_doc_mod, "_collect_report", return_value=report):
            assert cmd_doctor(_make_args(json_out=True)) == 1

    def test_exit_code_two_when_python_too_old(self):
        report = _ok_report()
        report["python"]["too_old"] = True
        report["python"]["ok"] = False
        report["overall_ok"] = False
        with mock.patch.object(_cmd_doc_mod, "_collect_report", return_value=report):
            assert cmd_doctor(_make_args(json_out=True)) == 2


class TestCmdDoctorInstallGit:
    def test_install_git_already_installed(self, capsys):
        with mock.patch.object(_cmd_doc_mod, "_collect_report", return_value=_ok_report()):
            exit_code = cmd_doctor(_make_args(install_git=True, json_out=True))
            captured = capsys.readouterr()
        assert "install_git" not in captured.out
        assert exit_code == 0

    def test_install_git_failure(self, capsys):
        from pandaone import git_installer as _gi_mod
        from pandaone.git_installer import GitInstallError
        report = _ok_report()
        report["git"]["installed"] = False
        report["git"]["version"] = None
        report["overall_ok"] = False
        with mock.patch.object(_cmd_doc_mod, "_collect_report", return_value=report), \
             mock.patch.object(_gi_mod, "install",
                        side_effect=GitInstallError("test install failure")):
            exit_code = cmd_doctor(_make_args(install_git=True, json_out=True))
            captured = capsys.readouterr()
        assert "failed" in captured.out or "error" in captured.out.lower()
        assert exit_code == 1


class TestCmdDoctorCleanConflicts:
    def test_clean_conflicts_runs_and_reports(self, capsys):
        with mock.patch.object(_cmd_doc_mod, "_collect_report", return_value=_ok_report()):
            exit_code = cmd_doctor(_make_args(clean_conflicts=True, json_out=True))
            captured = capsys.readouterr()
        assert exit_code == 0
        assert "clean_conflicts" in captured.out

    def test_clean_conflicts_not_triggered_by_default(self, capsys):
        """默认不该跑清理分支（mock.Mock 的属性陷阱防护）。"""
        with mock.patch.object(_cmd_doc_mod, "_collect_report", return_value=_ok_report()):
            cmd_doctor(_make_args(json_out=True))
            captured = capsys.readouterr()
        assert "clean_conflicts" not in captured.out


class TestPrintHumanReport:
    def test_prints_to_stdout(self, capsys):
        _print_human_report(_ok_report())
        captured = capsys.readouterr()
        assert "0.7.7" in captured.out
        assert "Python" in captured.out
        assert "Git" in captured.out


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
