# -*- coding: utf-8 -*-
"""
test_installer_iss.py — 安装器脚本 codeaudit.iss 的回归测试 (v0.7.34.0 / R1)

为什么必须有这个文件
--------------------
R1 缺陷：静默安装（``/VERYSILENT``，企业批量部署场景）时 IDE 的 MCP 配置
不会被更新 —— IDE 里跑的还是旧版 MCP，0.7.31.0 修的 GBK/UTF-8 编码 bug 继续生效。

根因有**两层**，缺一不可（两层都在 Inno Setup 6 上实测过）：

  1) ``[Run]`` 的 install-mcp 条目挂了 ``skipifsilent``
     -> 静默安装时整条被跳过（IS 文档：skipifsilent = "skip this entry if
     Setup is running (very) silent"）。

  2) ``[Run]`` 条目带 ``Tasks: installmcp`` 时，**只有该任务被选中才会执行**
     （IS 文档："If the end user selects a task from this list, the entry is
     processed"）。而 installmcp 任务带 ``Flags: unchecked``
     -> 静默安装里默认不选中 -> 实测该条目**根本不执行**。

所以**只去掉 skipifsilent 是修不好的**：必须同时去掉任务的 ``unchecked``。
本文件把这两条、以及"install-mcp 必须排在 doctor --clean-conflicts 之前"
锁死成断言，防止以后回退。

实测记录（本机 Inno Setup 6，探针安装包 work/isem、work/isem2）：
  postinstall + 无 Tasks              -> 静默安装下执行
  postinstall + Tasks: 默认选中任务   -> 静默安装下执行
  postinstall + Tasks: unchecked 任务 -> 静默安装下**不执行**
  postinstall + Tasks: checkedonce    -> 首次安装执行，**升级安装不执行**
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ISS = ROOT / "src" / "pandaone" / "installer" / "codeaudit.iss"


def _sections() -> tuple[str, str]:
    """返回 ([Tasks] 正文, [Run] 正文)。"""
    text = ISS.read_text(encoding="utf-8")
    tasks = text.split("[Tasks]", 1)[1].split("[Files]", 1)[0]
    run = text.split("[Run]", 1)[1].split("[UninstallRun]", 1)[0]
    return tasks, run


def _run_entries(run_body: str) -> list[str]:
    """[Run] 段里所有 Filename: 条目（整行）。"""
    return [
        line.strip()
        for line in run_body.splitlines()
        if line.strip().startswith("Filename:")
    ]


# ---------------------------------------------------------------------------
# 要求 1：install-mcp 必须在静默安装时也执行
# ---------------------------------------------------------------------------

def test_install_mcp_entry_has_no_skipifsilent():
    """install-mcp 的 [Run] 条目不能带 skipifsilent。"""
    _, run = _sections()
    entries = [ln for ln in _run_entries(run) if "install-mcp" in ln]
    assert len(entries) == 1, f"应有且只有一条 install-mcp [Run] 条目，实际 {len(entries)} 条"
    line = entries[0]
    assert "skipifsilent" not in line, (
        "install-mcp 的 [Run] 条目不能带 skipifsilent —— "
        "静默安装（/VERYSILENT）下整条会被跳过，IDE 的 MCP 配置就不会被更新"
    )
    for flag in ("postinstall", "nowait", "runascurrentuser", "runmaximized"):
        assert flag in line, f"install-mcp 条目应保留 {flag} 标志: {line}"


def test_installmcp_task_is_selected_in_silent_installs():
    """installmcp 任务不能是 unchecked / checkedonce。

    unchecked  -> 静默安装里默认不选中 -> [Run] 条目根本不执行（IS 实测）。
    checkedonce -> 升级安装时变成不选中 -> 升级场景同样不执行（IS 实测）。
    """
    tasks, _ = _sections()
    lines = [
        ln for ln in tasks.splitlines()
        if ln.strip().startswith('Name: "installmcp"')
    ]
    assert len(lines) == 1, f"应有且只有一条 installmcp 任务定义，实际 {len(lines)} 条"
    line = lines[0]
    assert "unchecked" not in line, (
        "installmcp 任务不能带 unchecked —— [Run] 条目带 Tasks: 时只有该任务被选中"
        "才会执行；unchecked 任务在静默安装里默认不选中（Inno Setup 6 实测："
        "该条目在 /VERYSILENT 下根本不执行，光去掉 skipifsilent 修不好）"
    )
    assert "checkedonce" not in line, (
        "installmcp 任务不能带 checkedonce —— 该标志会让任务在"
        "「检测到已安装旧版本」时变成不选中，升级安装同样不执行"
    )


def test_install_mcp_uses_absolute_command():
    """install-mcp 必须带 --absolute-command（写绝对路径，而不是裸名）。"""
    _, run = _sections()
    entries = [ln for ln in _run_entries(run) if "install-mcp" in ln]
    assert len(entries) == 1
    assert "--absolute-command" in entries[0], (
        "install-mcp 必须带 --absolute-command，否则 IDE 配置里写的是裸名 "
        "pandaone-mcp，会按 PATH 命中旧 pip 版 MCP"
    )


# ---------------------------------------------------------------------------
# 要求 3：顺序 —— install-mcp 必须排在 doctor --clean-conflicts 之前
# ---------------------------------------------------------------------------

def test_install_mcp_runs_before_clean_conflicts():
    """先写绝对路径，再清理 PATH 里的旧 pip 版。

    doctor --clean-conflicts 会把 PATH 里抢占命令的旧 pandaone.exe /
    pandaone-mcp.exe 改名备份成 *.bak-pandaone-<ver>。如果它先跑，
    IDE 配置里残留的裸名就可能指向被改名的文件。
    """
    _, run = _sections()
    entries = _run_entries(run)
    idx_mcp = next(i for i, ln in enumerate(entries) if "install-mcp" in ln)
    idx_clean = next(i for i, ln in enumerate(entries) if "doctor --clean-conflicts" in ln)
    assert idx_mcp < idx_clean, (
        "install-mcp 必须排在 doctor --clean-conflicts 之前："
        "先把 IDE 配置改写成 {app}\\pandaone-mcp.exe 绝对路径，"
        "再去改名备份 PATH 里的旧 pip 版"
    )


def test_clean_conflicts_still_runs_in_silent_installs():
    """doctor --clean-conflicts 必须继续在静默安装里执行（既有约束，别回退）。"""
    _, run = _sections()
    entries = [ln for ln in _run_entries(run) if "doctor --clean-conflicts" in ln]
    assert len(entries) == 1, f"应有且只有一条 doctor --clean-conflicts 条目，实际 {len(entries)} 条"
    assert "skipifsilent" not in entries[0], (
        "doctor --clean-conflicts 不能带 skipifsilent —— "
        "静默安装正是最需要清理 PATH 冲突的场景"
    )


if __name__ == "__main__":
    import sys

    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
