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
import re
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

#: 提示行的识别正则 —— 只认**行首**的 [INFO]/[WARN]/[ERROR] 标记。
#: 用 [ \t]*（不是 \s*）避免跨行匹配：JSON 字段值里恰好带方括号不算污染。
_NOTICE_LINE_RE = re.compile(r"(?m)^[ \t]*\[(INFO|WARN|ERROR)\]")


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


def _write_writable_desktop_ini(root):
    """在项目根写一个**可写**的 desktop.ini（复现 M1 的现场）。"""
    ini = root / "desktop.ini"
    if ini.exists():
        try:
            from pandaone.desktop_icon import remove_desktop_icon
            remove_desktop_icon(root)
        except Exception:
            pass
    ini.write_text("[.ShellClassInfo]\r\nIconFile=x\r\n", encoding="utf-8")
    return ini


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
            # desktop.ini 是 lock **之后**由 apply_desktop_icon 写的，
            # 而且它必须保持可写（否则 Explorer 写不回去）。
            # 它带 system/hidden 属性，直接覆盖写会 PermissionError ——
            # 先用 remove_desktop_icon 清属性+删除，再写一个可写的副本，
            # 复现 M1 的真实状态："lock 之后项目根有一个可写的 desktop.ini"。
            _write_writable_desktop_ini(p)
            assert (p / "desktop.ini").exists()
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
        capsys.readouterr()          # 冲掉 init 的输出，只留 doctor 的 JSON

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
        capsys.readouterr()          # 冲掉 init 的输出，只留 doctor 的 JSON
        _doc.cmd_doctor(_args(p, json_out=True))
        out = capsys.readouterr().out
        data = json.loads(out)
        assert isinstance(data, dict)
        assert "steps" not in data, "没有步骤时不应凭空造 steps 字段"


# ============================================================
# v0.7.34.0 返工 — doctor --json 的 stdout 严格只有一个 JSON 文档
# ============================================================
#
# 复现（用户侧实测，新 HOME + 无指纹文件）:
#     [INFO] 已生成 pandaone 指纹: 62c1ffff50637824...   <- 打在 stdout
#     { "pandaone": { ... } }
#   json.loads(整个 stdout) -> Expecting value: line 1 column 2 (char 1)
#
# 为什么这是真问题:
#   这行 INFO 只在"指纹不存在 / 需要刷新"时打印 —— 恰好就是**用户刚升级完**
#   的第一个窗口。机器端（CI / IDE 插件 / MCP）升级后第一次跑就炸，第二次才正常。
#
# 覆盖的三条 stdout 污染路径:
#   1) check_fingerprint 的 info 提示（公共启动路径）
#   2) TTY 下的 banner + README 摘要（实测能把 stdout 撑到 116 行）
#   3) git gate 的 "git 缺失" 提示


class TestDoctorJsonStdoutPurity:
    """`pandaone doctor --json` 的 stdout 必须能被 json.loads 整体解析成**单个**对象。"""

    def test_fingerprint_notice_goes_to_stderr_not_stdout(self, tmp_path, monkeypatch, capsys):
        """指纹提示必须走 stderr —— stdout 只留"命令的正题"。"""
        from pandaone import cli as _cli

        fp_path = tmp_path / ".pandaone_fp.txt"
        monkeypatch.setattr(_cli, "FP_PATH", fp_path)
        assert _cli.check_fingerprint() is True
        captured = capsys.readouterr()
        assert captured.out == "", (
            "指纹提示不应出现在 stdout 上（会破坏 json.loads(stdout)）:\n"
            + captured.out
        )
        assert "[INFO]" in captured.err, (
            "指纹提示应该走 stderr（终端里照样看得见，用户可见提示不能丢）:\n"
            + captured.err
        )

    def test_doctor_json_stdout_is_one_object_with_fresh_home(self, tmp_path):
        """端到端: 全新 HOME（无指纹文件）+ --json -> stdout 整段可 json.loads。

        v0.7.34.1 跨平台修复（CI Linux 红 / Windows 绿）:
          隔离家目录必须**同时**设两个环境变量 ——
            HOME        → Linux / macOS: posixpath.expanduser("~") 读它
            USERPROFILE → Windows:      ntpath.expanduser("~") 优先读它
          只设 USERPROFILE 时，Linux 上 Path.home() 仍指向真实 HOME，指纹文件
          还在那儿（tests/conftest.py 的 session fixture 开跑前就把指纹**播种**
          到真实 HOME 了）→ 走不到"首次运行"分支 → stderr 里没有 [INFO] 提示
          → 老断言 assert "[INFO]" in r.stderr 在 Linux CI 上必红。

          HOMEDRIVE / HOMEPATH **不用**设: ntpath.expanduser 的 Windows 分支是
          "USERPROFILE 优先，缺失才回退 HOMEDRIVE+HOMEPATH" —— 本用例永远设了
          USERPROFILE，那条回退分支根本走不到；设了反而会毁掉子进程里其它工具
          （git / cmd）可能用到的回退信息。
        """
        import os
        import subprocess

        home = tmp_path / "home"
        home.mkdir()
        proj = tmp_path / "proj"
        proj.mkdir()
        env = dict(os.environ)
        # 隔离真实指纹文件 -> 走"首次运行"分支（两个平台各认各的变量）
        env["HOME"] = str(home)          # Linux / macOS: Path.home() 读它
        env["USERPROFILE"] = str(home)   # Windows: ntpath.expanduser("~") 优先项
        env["PYTHONPATH"] = str(ROOT / "src")
        env["PANDAONE_SKIP_GIT_CHECK"] = "1"
        r = subprocess.run(
            [sys.executable, "-m", "pandaone", "doctor", "--json", "--root", str(proj)],
            capture_output=True, text=True, encoding="utf-8",
            env=env, timeout=180,
        )
        assert r.returncode in (0, 1, 3), (
            "doctor 退出码应是 0/1/3，实际 %r:\n%s" % (r.returncode, r.stderr)
        )
        data = json.loads(r.stdout)        # 整段 stdout 只能是一个 JSON 文档
        assert isinstance(data, dict)
        assert "layers" in data
        assert "overall_ok" in data
        # --- stdout 纯度：这才是"升级后首跑 doctor --json 可被机器解析"的守门 ---
        # 提示行（[INFO]/[WARN]/[ERROR]）一旦混进 stdout，json.loads(stdout) 必炸
        # ("Expecting value: line 1 column 2")。
        assert not _NOTICE_LINE_RE.search(r.stdout), (
            "stdout 混进了提示行（会破坏 json.loads(stdout)）:\n" + r.stdout[:400]
        )
        # --- 「提示若出现，必须在 stderr」---
        # 不强制提示**必须**出现: 指纹文件已存在时（任何原因）就本来没有提示 ——
        # 那是产品正确行为，不是缺陷。老断言把"提示必须存在"和"提示必须在
        # stderr"绑死了，所以指纹已存在时会在 Linux CI 上假红。
        # "提示确实走了 stderr" 由同文件的 in-process 用例守住:
        # test_fingerprint_notice_goes_to_stderr_not_stdout（monkeypatch 了
        # FP_PATH，不依赖 HOME，Linux CI 上同样是绿的）。
        for line in r.stderr.splitlines():
            if _NOTICE_LINE_RE.search(line):
                assert line not in r.stdout, (
                    "提示同时出现在 stdout 和 stderr —— 说明污染了 stdout:\n" + line
                )
        # --- 隔离确实生效（平台无关的证据）---
        # 指纹文件被写进**隔离出来的**家目录 ⇒ 子进程确实把 HOME / USERPROFILE
        # 当成了家目录 ⇒ 走的是"首次运行自动生成指纹"分支（而不是"指纹已存在"
        # 分支）。这条不依赖 stderr 文案，两个平台都成立。
        assert (home / ".pandaone_fp.txt").exists(), (
            "子进程没在隔离家目录里生成指纹文件（隔离没生效？）:\n%s" % home
        )

    def test_doctor_json_stdout_is_one_object_in_tty(self, tmp_path, monkeypatch, capsys):
        """TTY 下跑 doctor --json: banner 走 stderr, stdout 仍是纯 JSON。"""
        import pandaone.__main__  # noqa: F401  (注册 doctor 子命令)
        from pandaone import cli as _cli

        monkeypatch.setattr(_cli, "FP_PATH", tmp_path / ".pandaone_fp.txt")
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)

        rc = _cli.main(["doctor", "--json", "--root", str(tmp_path)])
        assert rc in (0, 1, 3), rc
        captured = capsys.readouterr()
        data = json.loads(captured.out)    # TTY 下也不能被 banner 污染
        assert isinstance(data, dict)
        assert "layers" in data
        assert "pandaone" in captured.err or "█" in captured.err, (
            "banner 应改走 stderr（终端里照样看得见）:\n" + captured.err[:400]
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
