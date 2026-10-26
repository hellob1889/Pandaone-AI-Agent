# -*- coding: utf-8 -*-
"""
test_install_hook_frozen.py
===========================
v0.7.32.0 真机安装回归抓到的真 bug 的回归测试。

Bug
---
``pandaone install-hook`` 在 **PyInstaller 打包的 exe 形态**下完全不可用：

    $ pandaone.exe install-hook --root D:\\some\\repo
    pandaone: error: argument command: invalid choice: 'pandaone.install_hook'

根因
----
``src/pandaone/cli_chunks/part_005.py::cmd_install_hook`` 用子进程调用
``install_hook.py``::

    cmd = [sys.executable, "-m", "pandaone.install_hook", "--root", args.root]

源码 / pip 形态下 ``sys.executable`` 是 python.exe，``-m`` 有模块执行语义，没问题；
但 **frozen 形态下 ``sys.executable`` 就是 pandaone.exe 本身** —— 它没有
``-m`` 模块执行语义，argparse 于是把 ``pandaone.install_hook`` 当成子命令名，
以 "invalid choice" 失败。

影响面（真机实测）：
  * CLI 的 ``install-hook`` 子命令
  * MCP 的 ``pandaone_install_hook`` 工具（它经 _run_cli 调 CLI，同样踩雷）
 两条链路全废 —— exe 用户在 L3 pre-commit 防御上根本装不上 hook。

为什么 ``doctor`` 没报出来
-------------------------
doctor 的 L3 检查只验证 "hook 文件在不在"，**不验证 "安装命令能不能跑"**。
所以装不上 hook 的机器，doctor 依然显示 ``[OK] L3_pre_commit_hook``。
（这条是本 bug 长期潜伏的直接原因。）

同类代码里 ``cmd_setup.py`` / ``cmd_upgrade.py`` / ``pandaone_mcp\\__main__.py``
早就有 frozen 感知（用 ``sys.executable serve`` 或同目录 ``pandaone.exe``），
只有 install-hook 这一条漏了。

修法
----
frozen 形态下改成**进程内直接调用** install_hook 模块的函数，
不再起子进程（详见 part_005.py::_load_install_hook_module 的注释）。

测试策略
--------
1. 静态校验：part_005.py 的 frozen 分支不再出现 ``sys.executable -m``；
2. 行为校验：模拟 frozen 形态，断言 cmd_install_hook 进程内调用了
   install_hook / uninstall_hook，且**没有**起子进程；
3. 行为校验：_load_install_hook_module 在源码形态下能真正加载到模块，
   且加载出的模块 TEMPLATE 常量指向真实存在的 hook 模板。
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
_PART_005 = _ROOT / "src" / "pandaone" / "cli_chunks" / "part_005.py"

if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


# ---------------------------------------------------------------------------
# 1. 静态校验：frozen 分支不得再用 sys.executable -m
# ---------------------------------------------------------------------------

def test_part005_has_frozen_awareness_in_install_hook():
    """cmd_install_hook 必须有 frozen 形态感知。"""
    src = _PART_005.read_text(encoding="utf-8")
    assert "_load_install_hook_module" in src, (
        "cmd_install_hook 缺少 frozen 形态的进程内调用路径"
    )
    assert 'getattr(sys, "frozen", False)' in src, (
        "cmd_install_hook 缺少 frozen 判定"
    )


def test_frozen_branch_does_not_use_sys_executable_m():
    """frozen 分支里不得出现 `sys.executable -m`（exe 没有模块执行语义）。"""
    src = _PART_005.read_text(encoding="utf-8")

    # 定位 cmd_install_hook 函数体
    start = src.find("def cmd_install_hook(args):")
    assert start > 0, "cmd_install_hook 未找到"
    body = src[start:start + 3000]

    # frozen 分支的起点
    frozen_idx = body.find('getattr(sys, "frozen", False)')
    assert frozen_idx > 0, "cmd_install_hook 内未找到 frozen 判定"

    # 非 frozen 的 subprocess 构造点（frozen 分支的终点）
    sub_idx = body.find('cmd = [sys.executable, "-m"', frozen_idx)
    assert sub_idx > 0, "非 frozen 的 subprocess 路径未找到"
    frozen_block = body[frozen_idx:sub_idx]

    # 剥离注释行 —— 注释里可以（也应该）写明"为什么不能用 sys.executable -m"，
    # 检查的是**可执行代码**，不是注释文本。
    code_lines = []
    for line in frozen_block.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        code_lines.append(stripped)
    code = "\n".join(code_lines)

    assert '"-m"' not in code, (
        "frozen 分支的代码里出现了 `-m` 模块执行调用，exe 形态下会以 "
        "invalid choice 失败:\n" + code
    )
    assert "sys.executable" not in code, (
        "frozen 分支的代码里出现了 sys.executable，exe 形态下不能拿它起子进程:\n"
        + code
    )


# ---------------------------------------------------------------------------
# 2. 行为校验：模拟 frozen 形态，断言进程内调用
# ---------------------------------------------------------------------------

def _load_part005_namespace():
    """把 cli_chunks/part_005.py exec 进一个独立命名空间。

    不能直接 `import pandaone.cli_chunks.part_005` —— cli.py 才是真正的
    装配器（它 exec 所有 chunk）。这里只取 part_005 自己需要的那些名字。

    真实运行时 cli.py 的模块级 `import sys` / `from pathlib import Path`
    就是 chunk 的执行环境，所以夹具必须补齐这两样，否则 chunk 里的
    `sys.executable` / `Path(...)` 会 NameError。
    """
    namespace = {
        "__name__": "pandaone.cli",
        "__file__": str(_PART_005),
        "sys": sys,
        "Path": Path,
        "os": __import__("os"),
        "time": __import__("time"),
    }
    # cli.py 的模块级环境还提供 i18n 的 t()（chunk 里的所有 print 都走它）
    try:
        from pandaone.i18n import t as _t

        namespace["t"] = _t
    except Exception:  # pragma: no cover - src 不在 path 上时的兜底
        namespace["t"] = lambda key, **kw: key
    exec(compile(_PART_005.read_text(encoding="utf-8"), str(_PART_005), "exec"), namespace)
    return namespace


def test_frozen_install_hook_calls_inprocess_without_subprocess(monkeypatch, tmp_path):
    """frozen 形态下：进程内调用 install_hook，且不起任何子进程。"""
    ns = _load_part005_namespace()

    # 模拟 frozen
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    called = {}

    def _fake_install_hook(root):
        called["install"] = root
        return 0

    def _fake_uninstall_hook(root):
        called["uninstall"] = root
        return 0

    class _FakeModule:
        install_hook = staticmethod(_fake_install_hook)
        uninstall_hook = staticmethod(_fake_uninstall_hook)

    monkeypatch.setitem(ns, "_load_install_hook_module", lambda: _FakeModule)

    # 起子进程就会炸 —— frozen 分支绝不能走 subprocess
    def _boom(*a, **k):
        raise AssertionError("frozen 分支起了子进程，这正是本 bug 的根因")

    monkeypatch.setattr("subprocess.run", _boom)
    monkeypatch.setattr("subprocess.Popen", _boom)

    class _Args:
        root = str(tmp_path)
        uninstall = False

    rc = ns["cmd_install_hook"](_Args())
    assert rc == 0, f"frozen install-hook 返回码应为 0，实际 {rc}"
    assert "install" in called, "frozen 分支没有调用 install_hook()"
    assert called["install"] == tmp_path.resolve()

    # 再验卸载分支
    _Args.uninstall = True
    rc = ns["cmd_install_hook"](_Args())
    assert rc == 0, f"frozen uninstall-hook 返回码应为 0，实际 {rc}"
    assert "uninstall" in called, "frozen 分支没有调用 uninstall_hook()"


def test_frozen_install_hook_reports_error_when_module_missing(monkeypatch, tmp_path):
    """冻结包内缺 install_hook.py 时，必须明确报错而不是静默失败。"""
    ns = _load_part005_namespace()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setitem(ns, "_load_install_hook_module", lambda: None)

    class _Args:
        root = str(tmp_path)
        uninstall = False

    rc = ns["cmd_install_hook"](_Args())
    assert rc == 1, "模块缺失时必须返回非 0"


# ---------------------------------------------------------------------------
# 3. 行为校验：模块加载器本身可用
# ---------------------------------------------------------------------------

def test_load_install_hook_module_resolves_template():
    """加载出的模块，其 TEMPLATE 常量必须指向真实存在的 hook 模板。"""
    ns = _load_part005_namespace()
    module = ns["_load_install_hook_module"]()
    assert module is not None, "_load_install_hook_module 加载失败"

    template = Path(module.TEMPLATE)
    assert template.is_file(), f"TEMPLATE 指向的模板不存在: {template}"
    check_script = Path(module.CHECK_SCRIPT)
    assert check_script.is_file(), f"CHECK_SCRIPT 指向的脚本不存在: {check_script}"


def test_source_mode_still_uses_subprocess_path():
    """非 frozen 形态必须保留原有的 subprocess 路径（回归保护）。"""
    ns = _load_part005_namespace()
    src = _PART_005.read_text(encoding="utf-8")
    assert '"-m", "pandaone.install_hook"' in src, (
        "非 frozen 的 subprocess 路径被误删，源码形态会失效"
    )


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
