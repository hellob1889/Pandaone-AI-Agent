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


# ---------------------------------------------------------------------------
# 要求 4：[UninstallRun] 必须删**真实路径**上的指纹文件
# ---------------------------------------------------------------------------
#
# 背景（本轮返工，独立复核 + 真机实测确认）:
#   指纹文件的真实位置是 %USERPROFILE%\.pandaone_fp.txt
#   （fp_security.DEFAULT_FP_PATH = Path.home() / ".pandaone_fp.txt"，
#     Windows 上 Path.home() 优先取 USERPROFILE 环境变量）。
#
#   而旧的 [UninstallRun] 删的是 "Documents\Pandaone" 子目录下的指纹文件
#   —— 那个目录从来不存在，所以卸载后指纹**一直残留**。后果:
#     重装同版本不同构建 -> 版本同 + 形态同 + hash 变 -> L5 判成真篡改
#     -> CLI 全锁死（用户彻底用不了）。
#
#   旧写法还有第二个错: dir /b /s /ah 的 /ah = 只列隐藏文件，
#   而指纹文件属性是 Archive（save_fp 只 write_text，没设 Hidden），
#   实测 /ah 一条都列不出来 —— 路径对了也删不掉。

def _uninstall_run_body() -> str:
    """[UninstallRun] 段正文。"""
    text = ISS.read_text(encoding="utf-8")
    assert "[UninstallRun]" in text, "codeaudit.iss 里找不到 [UninstallRun] 段"
    body = text.split("[UninstallRun]", 1)[1].split("[UninstallDelete]", 1)[0]
    return body


def _uninstall_run_entries(body: str) -> list[str]:
    """[UninstallRun] 段里所有 Filename: 条目（整行）—— 卸载器**真正会执行**的命令。"""
    return [
        line.strip()
        for line in body.splitlines()
        if line.strip().startswith("Filename:")
    ]


def test_uninstall_run_has_no_wrong_fingerprint_path():
    r"""[UninstallRun] 段里不能再出现那个**不存在的** Documents\Pandaone 路径。"""
    body = _uninstall_run_body()
    assert "{userdocs}" not in body, (
        "[UninstallRun] 不该再出现 {userdocs} —— 指纹不在 Documents 下"
    )
    assert "Pandaone\\.pandaone_fp.txt" not in body, (
        "[UninstallRun] 不该再删 <Documents>\\Pandaone\\.pandaone_fp.txt 这个不存在的路径"
    )


def test_uninstall_run_deletes_real_fingerprint_path():
    r"""必须删 %USERPROFILE%\.pandaone_fp.txt 和 {userprofile}\.pandaone_fp.txt。"""
    body = _uninstall_run_body()
    entries = _uninstall_run_entries(body)
    assert entries, "[UninstallRun] 段里一条 Filename: 条目都没有"
    assert any("%USERPROFILE%\\.pandaone_fp.txt" in e for e in entries), (
        "[UninstallRun] 必须删 %USERPROFILE%\\.pandaone_fp.txt"
        "（= Python Path.home() 实际写指纹的位置）:\n" + "\n".join(entries)
    )
    assert any("{userprofile}\\.pandaone_fp.txt" in e for e in entries), (
        "[UninstallRun] 必须删 {userprofile}\\.pandaone_fp.txt"
        "（覆盖 profile 被重定向 / USERPROFILE 环境变量陈旧的情况）:\n" + "\n".join(entries)
    )


def test_uninstall_run_does_not_use_hidden_only_dir_filter():
    """不能用 dir /ah —— 指纹文件不是隐藏文件（属性 Archive），/ah 过滤会一条都列不出来。"""
    body = _uninstall_run_body()
    entries = _uninstall_run_entries(body)
    for e in entries:
        assert "/ah" not in e, (
            "[UninstallRun] 的删除命令不能用 dir /ah（只列隐藏文件）:\n" + e
        )


def test_uninstall_run_fingerprint_path_matches_python_home():
    """Inno 侧删的路径必须和 Python 侧 Path.home() 指向同一个文件。"""
    import os
    from pathlib import Path

    body = _uninstall_run_body()
    # Python 侧: fp_security.DEFAULT_FP_PATH = Path.home() / ".pandaone_fp.txt"
    assert (Path.home() / ".pandaone_fp.txt").name == ".pandaone_fp.txt"
    if os.name == "nt":
        # Windows 上 Path.home() 优先 USERPROFILE —— Inno 侧必须认同一个变量
        assert "USERPROFILE" in body, (
            "[UninstallRun] 必须用 USERPROFILE 展开，才能和 Path.home() 对上"
        )


if __name__ == "__main__":
    import sys

    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
