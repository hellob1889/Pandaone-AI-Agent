# -*- coding: utf-8 -*-
"""
test_cmd_doctor_tristate.py — `pandaone doctor` 三态语义 + M1~M5 回归测试
======================================================================

为什么必须有这个文件
--------------------
上一批改动把 doctor 从「存在性体检」改造成「可执行性体检」（8 层真检查 +
退出码 3），方向正确，但独立复核发现 **5 个必须修的缺陷** —— 核心是：

  **doctor 在真实用户机器上会永远红**，新增的退出码 3 因此没有可用语义。

复现（复核方已实测）：
    [FAIL] L1_file_lock        : 0/0 protected files writable
    [FAIL] L2_watchdog_rollback: no baseline commit; watchdog NOT running
    [FAIL] L3_pre_commit_hook  : hook NOT installed
    [FAIL] L4_startup_check    : README NOT found in project root
    exit=3

而 `pandaone setup` 的步骤表**不跑 lock、不跑 install-hook** ⇒ 没有任何官方
流程能让 doctor 返回 0。

覆盖的缺陷：
  M1  `pandaone lock` 自己造出可写的 desktop.ini → L1 永久 FAIL
      （desktop.ini 在默认 protected_extensions 里，且是加锁**之后**才写的）
  M2  L7 在 pip 安装形态下恒 FAIL → 所有 PyPI 用户 doctor 永远 exit 3
      （repo_root 落到 .../Lib，找不到 .github/workflows/audit.yml）
  M3  「没启用」与「坏了」混为一谈 → 正常项目必然 exit 3
  M4  L1 在「零受保护文件」时报 FAIL
  M5  `doctor --json --clean-conflicts` 输出两份 JSON → json.loads 报
      "Extra data: line 2 column 1"

三态语义（本轮核心）：
  na   = 该层防护**从未配置过** → [N/A]，不计入失败、不影响退出码
  ok   = 配置过且检查通过
  fail = **配置过但坏了** → [FAIL]，才计入失败、才影响退出码
"""
import importlib.util
import json
import shutil
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


# ============================================================
# 辅助
# ============================================================

def _init_project(root):
    """用**真实**的 `pandaone init` 建一个项目（不是手工拼 config.json）。"""
    from pandaone.cli import cmd_init
    args = SimpleNamespace(root=str(root), ext=None, no_binary=False)
    assert cmd_init(args) == 0
    return root


def _lock(root):
    from pandaone.cli import cmd_lock
    return cmd_lock(SimpleNamespace(root=str(root), no_auto_init=True))


def _unlock(root):
    from pandaone.cli import cmd_unlock
    try:
        return cmd_unlock(SimpleNamespace(root=str(root)))
    except Exception:
        return None


def _args(root, json_out=False, clean=False):
    return SimpleNamespace(root=str(root), json=json_out, install_git=False,
                           clean_conflicts=clean, lang="en")


def _na_machine_layers(monkeypatch):
    """把**机器级**的层（L5 指纹 / L7 CI / L8 PATH）固定成 N/A。

    这三层的结果取决于本机状态（指纹文件、源码树、PATH），跟"项目有没有
    启用这层防护"无关。固定成 N/A 之后，项目级三态的断言就与机器状态解耦，
    不会因为"这台机器恰好没装指纹文件"而假红。
    """
    for name in ("_check_layer5_self_fingerprint", "_check_layer7_ci_audit",
                 "_check_layer8_path_conflict"):
        monkeypatch.setattr(
            _doc, name,
            lambda *a, **k: _doc._na_layer("N/A - machine-level layer (test stub)"))


def _state(info):
    """取层级三态；老实现没有 state 字段时按 ok/na 推导（便于对比断言）。"""
    if "state" in info:
        return info["state"]
    if info.get("na"):
        return "na"
    return "ok" if info.get("ok") else "fail"


# ============================================================
# M1 — lock 自己造出可写的 desktop.ini → L1 永久 FAIL
# ============================================================

class TestM1DesktopIni:
    def test_init_default_excludes_desktop_ini(self, tmp_path):
        """治本：init 生成的默认 exclude_patterns 必须含 desktop.ini。"""
        _init_project(tmp_path)
        cfg = json.loads(
            (tmp_path / ".pandaone" / "config.json").read_text(encoding="utf-8"))
        assert "desktop.ini" in cfg["exclude_patterns"], cfg["exclude_patterns"]

    def test_desktop_ini_never_in_protected_set(self, tmp_path):
        """老项目（config 里没有 desktop.ini 排除项）也不能把它算成受保护文件。"""
        p = tmp_path
        (p / ".pandaone").mkdir(parents=True, exist_ok=True)
        cfg = {"protected_extensions": [".py", ".ini"], "exclude_patterns": []}
        (p / ".pandaone" / "config.json").write_text(
            json.dumps(cfg), encoding="utf-8")
        (p / "desktop.ini").write_text("[.ShellClassInfo]\r\n", encoding="utf-8")
        (p / "demo.py").write_text("print('demo')\n", encoding="utf-8")

        from pandaone.cli import _iter_protected_files
        files = _iter_protected_files(p, cfg)
        assert not any(f.name.lower() == "desktop.ini" for f in files), files

    def test_writable_desktop_ini_does_not_break_l1(self, tmp_path):
        """复现 M1 场景：lock 之后出现一个**可写**的 desktop.ini，L1 不能变红。"""
        p = _init_project(tmp_path)
        (p / "demo.py").write_text("print('demo')\n", encoding="utf-8")
        try:
            assert _lock(p) == 0
            # desktop.ini 是 lock 之后由 apply_desktop_icon 写的（必须可写）
            (p / "desktop.ini").write_text(
                "[.ShellClassInfo]\r\nIconFile=x\r\n", encoding="utf-8")
            info = _doc._check_layer1_file_lock(p)
            assert _state(info) != "fail", info["note"]
            assert info["ok"] is True, info["note"]
        finally:
            _unlock(p)


# ============================================================
# M2 — L7 在 pip 安装形态下恒 FAIL
# ============================================================

class TestM2PipFormLayer7:
    def test_l7_is_na_in_pip_form(self, tmp_path):
        """模拟 pip 形态：cmd_doctor.py 落在 site-packages/pandaone/ 下。"""
        pkg = tmp_path / "site-packages" / "pandaone"
        pkg.mkdir(parents=True)
        shutil.copy2(Path(_doc.__file__), pkg / "cmd_doctor.py")

        spec = importlib.util.spec_from_file_location(
            "pandaone_pip_form", str(pkg / "cmd_doctor.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # 前提：pip 形态的 repo_root 不是源码树
        repo_root = (pkg / "cmd_doctor.py").resolve().parent.parent.parent
        assert not (repo_root / "pyproject.toml").exists()
        assert not (repo_root / ".git").exists()

        info = mod._check_layer7_ci_audit()
        assert info.get("na") is True, info
        assert info["ok"] is True, info

    def test_l7_still_checks_workflow_in_source_tree(self, tmp_path):
        """对照组：源码树形态仍然真查 audit.yml（不能因为修 M2 就变成永真）。"""
        info = _doc._check_layer7_ci_audit()
        repo_root = Path(_doc.__file__).resolve().parent.parent.parent
        if (repo_root / "pyproject.toml").exists() or (repo_root / ".git").exists():
            assert info.get("na") is not True, info
            assert info["ok"] is True, info["note"]


# ============================================================
# M3 — 「没启用」与「坏了」混为一谈
# ============================================================

class TestM3TriState:
    def test_fresh_init_project_is_all_na_and_exit_zero(self, tmp_path, monkeypatch,
                                                         capsys):
        """刚 `pandaone init` 的普通项目 → 各层 na、失败层为空、exit 0。"""
        p = _init_project(tmp_path)
        _na_machine_layers(monkeypatch)

        report = _doc._collect_report(p)
        for name in LAYER_NAMES:
            assert _state(report["layers"][name]) == "na", (
                name, report["layers"][name])
        assert report["failed_layers"] == []
        assert report["overall_ok"] is True

        rc = _doc.cmd_doctor(_args(p, json_out=True))
        capsys.readouterr()
        assert rc == 0, f"刚 init 的正常项目必须 exit 0，实际 {rc}"

    def test_na_layers_are_not_reported_as_failures(self, tmp_path, monkeypatch):
        """N/A 的层不进失败列表，也不影响 overall_ok。"""
        p = _init_project(tmp_path)
        _na_machine_layers(monkeypatch)
        report = _doc._collect_report(p)
        assert report.get("na_layers"), "报告里应列出 na 层"
        assert set(report["na_layers"]).isdisjoint(set(report["failed_layers"]))
        assert report["overall_ok"] is True

    def test_replaced_hook_is_fail_and_exit_3(self, tmp_path, monkeypatch, capsys):
        """反向：装好的 hook 被换成 `exit 0` 空壳 → L3 必须是 **fail**（不是 na）。"""
        p = _init_project(tmp_path)
        _na_machine_layers(monkeypatch)

        hooks = p / ".git" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (p / ".pandaone" / "pre-commit-check.py").write_text(
            "print('ok')\n", encoding="utf-8")
        # 装好的 hook（带 Pandaone 标识）
        (hooks / "pre-commit").write_text(
            "#!/bin/sh\n# Pandaone AI Agent pre-commit hook\nexit 0\n", encoding="utf-8")
        # 回归场景：hook 被摘掉换成空壳
        (hooks / "pre-commit").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

        info = _doc._check_layer3_pre_commit(p)
        assert info.get("na") is not True, info
        assert info["ok"] is False, info
        assert "not ours" in info["note"]

        report = _doc._collect_report(p)
        assert "L3_pre_commit_hook" in report["failed_layers"]
        assert report["overall_ok"] is False

        rc = _doc.cmd_doctor(_args(p, json_out=True))
        capsys.readouterr()
        assert rc == 3, f"层失败必须 exit 3，实际 {rc}"

    def test_deleted_hook_after_install_is_fail(self, tmp_path, monkeypatch):
        """装过 hook 又被删掉 → 同样是 fail（门禁被摘掉不能装作没事）。"""
        p = _init_project(tmp_path)
        _na_machine_layers(monkeypatch)
        hooks = p / ".git" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "pre-commit").write_text(
            "#!/bin/sh\n# Pandaone AI Agent pre-commit hook\nexit 0\n", encoding="utf-8")
        (p / ".pandaone" / "pre-commit-check.py").write_text(
            "print('ok')\n", encoding="utf-8")
        # hook 被删掉（检查脚本还在 → 说明装过）
        (hooks / "pre-commit").unlink()

        info = _doc._check_layer3_pre_commit(p)
        assert info.get("na") is not True, info
        assert info["ok"] is False, info
        assert "NOT installed" in info["note"]


# ============================================================
# M4 — L1 在「零受保护文件」时报 FAIL
# ============================================================

class TestM4ZeroProtectedFiles:
    def test_zero_protected_files_is_na(self, tmp_path):
        """零受保护文件 = 没有可保护的东西 → N/A，不是 FAIL。"""
        p = _init_project(tmp_path)
        info = _doc._check_layer1_file_lock(p)
        assert info.get("na") is True, info
        assert info["ok"] is True, info
        assert "0/0" not in info["note"]

    def test_zero_protected_files_is_na_even_after_lock(self, tmp_path):
        """跑过 lock（lock_modes.json 在）但项目里没有受保护文件 → 仍是 N/A。"""
        p = _init_project(tmp_path)
        (p / ".pandaone" / "lock_modes.json").write_text("{}", encoding="utf-8")
        info = _doc._check_layer1_file_lock(p)
        assert info.get("na") is True, info


# ============================================================
# M5 — `doctor --json --clean-conflicts` 输出两份 JSON
# ============================================================

class TestM5SingleJsonDocument:
    def test_json_clean_conflicts_is_one_object(self, tmp_path, monkeypatch, capsys):
        """--json --clean-conflicts 的 stdout 必须能被 json.loads 整体解析。"""
        from pandaone import cmd_setup as _setup
        # 清理动作会真的改名机器上的 pandaone 可执行文件 —— 测试里必须打桩
        monkeypatch.setattr(_setup, "clean_path_conflicts",
                            lambda: ("ok", "mocked: no conflict"))
        p = _init_project(tmp_path)
        _na_machine_layers(monkeypatch)

        _doc.cmd_doctor(_args(p, json_out=True, clean=True))
        out = capsys.readouterr().out

        data = json.loads(out)          # 整段 stdout 只能是一个 JSON 文档
        assert isinstance(data, dict)
        assert "layers" in data
        assert "overall_ok" in data
        steps = data.get("steps") or []
        assert any(s.get("step") == "clean_conflicts" for s in steps), steps

    def test_json_plain_is_one_object(self, tmp_path, monkeypatch, capsys):
        """普通 --json（不带 --clean-conflicts）同样只能有一个 JSON 文档。"""
        p = _init_project(tmp_path)
        _na_machine_layers(monkeypatch)
        _doc.cmd_doctor(_args(p, json_out=True))
        out = capsys.readouterr().out
        data = json.loads(out)
        assert isinstance(data, dict)
        assert "steps" not in data, "没有步骤时不应凭空造 steps 字段"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
