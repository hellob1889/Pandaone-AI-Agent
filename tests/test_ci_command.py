"""
test_ci_command.py
==================
Phase 7 — pandaone ci 子命令（GitHub Actions CI 集成）。

第一性原理：
  CI 的目的是验证"每个变更都有审计"——不能在 PR 中绕过 pandaone write。
  ci 子命令对比 git changed files vs audit log，缺一项就 fail。

工作流：
  1. git diff --name-only origin/main..HEAD → 改动文件列表
  2. 过滤出受保护扩展名（text + binary）
  3. 对比每个文件是否在 pandaone.jsonl 有 APPROVED 记录
  4. 二进制：检查 binary_snapshots.json 中 SHA256 是否与最新 write 匹配
  5. 缺记录的文件 → 输出 + rc=1（fail CI）
  6. 全有 → rc=0（pass CI）

对抗式审查：
  - 攻击：agent 直接 git commit 绕过 write
    缓解：CI 拒绝合并，要求补 write
  - 攻击：删 pandaone.jsonl 抹除痕迹
    缓解：CI 比 git 历史里的 audit 文件
  - 攻击：PR 不基于 main 分支
    缓解：用 --base 参数显式指定基线分支
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"


def _run_cli(*args, cwd=None, env_extra=None):
    """运行 pandaone CLI"""
    import os as _os
    env = _os.environ.copy()
    env["PYTHONPATH"] = str(SRC_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    if env_extra:
        env.update(env_extra)
    cmd = [sys.executable, "-m", "pandaone", *args]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd or ROOT_DIR, env=env)
    return r.returncode, r.stdout, r.stderr


def _git_exe():
    """获取 git 绝对路径（v0.7.15: 动态探测，不再硬编码作者机器路径）"""
    import shutil
    c = shutil.which("git")
    if c:
        return c
    pytest.skip("git not found")


def _git(args, cwd, env_extra=None):
    """运行 git 命令"""
    import os as _os
    env = _os.environ.copy()
    env["PYTHONPATH"] = str(SRC_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    if env_extra:
        env.update(env_extra)
    r = subprocess.run([_git_exe()] + args, cwd=cwd, env=env, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def setup_git_project(tmp_path: Path) -> Path:
    """建 git 项目 + init + 初始文件 + 初始 commit"""
    # init pandaone
    rc, out, err = _run_cli("init", "--root", str(tmp_path), cwd=tmp_path)
    assert rc == 0, f"init 失败: {err}"

    # git init
    _git(["init"], cwd=tmp_path)
    _git(["config", "user.email", "ci@t.t"], cwd=tmp_path)
    _git(["config", "user.name", "ci"], cwd=tmp_path)

    # 初始文件
    (tmp_path / "main.py").write_text("INITIAL = 1\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Init\n", encoding="utf-8")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\nINIT_LOGO")

    _git(["add", "-A"], cwd=tmp_path)
    rc, _, err = _git(["commit", "-m", "init"], cwd=tmp_path)
    assert rc == 0, f"initial commit failed: {err}"

    return tmp_path


# ============================================================
# Step 45: RED 测试
# ============================================================

class TestCiSubcommandExists:
    """ci 子命令应存在"""

    def test_ci_help_exists(self):
        """--help 应包含 ci"""
        rc, out, err = _run_cli("--help")
        assert "ci" in out.lower(), f"ci 应在 --help 中: {out}"

    def test_ci_subcommand_help(self, tmp_path):
        """pandaone ci --help 应输出帮助"""
        rc, out, err = _run_cli("ci", "--help")
        # argparse 在没参数时也接受 --help
        assert "ci" in out.lower() or "audit" in out.lower() or "audit" in err.lower()


class TestCiWithNoChanges:
    """没有变更时应 pass"""

    def test_ci_no_changes_passes(self, tmp_path):
        """没有改动文件时 ci 应返回 rc=0"""
        setup_git_project(tmp_path)
        rc, out, err = _run_cli("ci", "--root", str(tmp_path))
        assert rc == 0, f"无变更应 pass，但 rc={rc}, out={out[-500:]}, err={err}"
        assert "PASS" in out or "pass" in out.lower() or "OK" in out


class TestCiWithApprovedChanges:
    """所有变更都有审计时应 pass"""

    def test_ci_approved_text_change_passes(self, tmp_path):
        """write 过的文本文件变更应 pass ci"""
        project = setup_git_project(tmp_path)
        # 通过 pandaone write 改 main.py
        rc, out, err = _run_cli(
            "write", "--root", str(project),
            "--file", "main.py",
            "--reason", "测试 CI 验证功能",
            "--problem", "需要确认 write 后 ci 通过",
            "--approach", "通过 pandaone write 修改并测试 ci",
            "--old", "INITIAL = 1",
            "--new", "INITIAL = 2",
        )
        assert rc == 0, f"write 失败: {err}"

        # ci 应 pass
        rc, out, err = _run_cli("ci", "--root", str(project))
        assert rc == 0, f"已审计的变更应 pass: {out[-500:]}\nstderr: {err}"

    def test_ci_approved_binary_change_passes(self, tmp_path):
        """write 过的二进制文件变更应 pass ci"""
        project = setup_git_project(tmp_path)
        # 准备新 logo
        new_logo = project / "new_logo.png"
        new_logo.write_bytes(b"\x89PNG\r\n\x1a\nNEW_LOGO")

        rc, out, err = _run_cli(
            "write", "--root", str(project),
            "--file", "logo.png",
            "--reason", "更新 logo 图标为新版设计",
            "--problem", "原 logo 图标已过时需要替换",
            "--approach", "用新版 logo 文件替换原文件",
            "--from-file", str(new_logo),
        )
        assert rc == 0, f"write binary 失败: {err}"

        # ci 应 pass
        rc, out, err = _run_cli("ci", "--root", str(project))
        assert rc == 0, f"二进制审计后应 pass: {out[-500:]}"


class TestCiWithUnauthorizedChanges:
    """有未审计变更时应 fail"""

    def test_ci_unapproved_text_change_fails(self, tmp_path):
        """直接修改 main.py（绕过 write）应 fail ci"""
        project = setup_git_project(tmp_path)
        # 绕开 write 直接改
        (project / "main.py").write_text("UNAUTHORIZED_CHANGE = True\n", encoding="utf-8")
        _git(["add", "main.py"], cwd=project)
        _git(["commit", "-m", "bypass"], cwd=project)

        rc, out, err = _run_cli("ci", "--root", str(project))
        assert rc != 0, f"未审计的变更应 fail，但 rc={rc}"
        assert "main.py" in out or "main.py" in err, "应指出违规文件"

    def test_ci_unapproved_binary_change_fails(self, tmp_path):
        """直接覆盖 logo.png 应 fail ci"""
        project = setup_git_project(tmp_path)
        (project / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\nHIJACKED")
        _git(["add", "logo.png"], cwd=project)
        _git(["commit", "-m", "bypass binary"], cwd=project)

        rc, out, err = _run_cli("ci", "--root", str(project))
        assert rc != 0, "未审计的二进制变更应 fail"

    def test_ci_unapproved_md_change_fails(self, tmp_path):
        """README.md 未审计变更应 fail（Phase 4.6 扩展保护）"""
        project = setup_git_project(tmp_path)
        (project / "README.md").write_text("# Hijacked\n", encoding="utf-8")
        _git(["add", "README.md"], cwd=project)
        _git(["commit", "-m", "bypass md"], cwd=project)

        rc, out, err = _run_cli("ci", "--root", str(project))
        assert rc != 0, "未审计的 md 变更应 fail"

    def test_ci_lists_all_offending_files(self, tmp_path):
        """ci 应列出所有违规文件（不是只列第一个）"""
        project = setup_git_project(tmp_path)
        # 同时改 3 个文件都不审计
        (project / "main.py").write_text("X = 1\n", encoding="utf-8")
        (project / "README.md").write_text("# X\n", encoding="utf-8")
        (project / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\nX")
        _git(["add", "-A"], cwd=project)
        _git(["commit", "-m", "bypass all"], cwd=project)

        rc, out, err = _run_cli("ci", "--root", str(project))
        assert rc != 0
        out_all = out + err
        # 应包含 3 个文件名（或至少 2 个）
        assert "main.py" in out_all
        assert "README.md" in out_all
        assert "logo.png" in out_all


class TestCiWithBaseBranch:
    """--base 参数指定基线分支"""

    def test_ci_uses_base_branch(self, tmp_path):
        """ci --base main 应基于 main 分支对比"""
        project = setup_git_project(tmp_path)
        # 创建 main 分支
        _git(["branch", "-M", "main"], cwd=project)

        # write 已经自动 commit 了
        rc, _, err = _run_cli(
            "write", "--root", str(project),
            "--file", "main.py",
            "--reason", "在 feature 分支上做修改准备 PR",
            "--problem", "准备开 PR 时需要先做一次合规修改",
            "--approach", "通过 pandaone write 修改后 git commit",
            "--old", "INITIAL = 1", "--new", "INITIAL = 3",
        )
        assert rc == 0, f"write 失败: {err}"

        # ci 应 pass（--base main 找到就直接用，HEAD~1 fallback 仅当 base 找不到时）
        rc, out, err = _run_cli("ci", "--root", str(project), "--base", "main")
        assert rc == 0, f"基于 main 对比应 pass: {out[-500:]}"

    def test_ci_explicit_base_overrides_head_minus_1(self, tmp_path):
        """PR #33 回归测试：--base 必须优先于 HEAD~1。

        Bug 之前：candidates[0] = "HEAD~1" 永远存在,即使传 --base main 也被顶替。
        修后：用户传的 base 优先于 HEAD~1 fallback。

        设计：用 detached HEAD 让 main 不跟随 forward。setup_git_project init 后
        checkout 到 detached HEAD,这样 evil.py commit 不会让 main 前进。

        关键：步骤 4 和 5 都用 main 作 base 但表现不同 — 证明 base 真的在用,
        不是 fallback 到 HEAD~1。
        """
        project = setup_git_project(tmp_path)
        _git(["branch", "-M", "main"], cwd=project)
        init_sha = _git(["rev-parse", "HEAD"], cwd=project)[1].strip()
        # detached HEAD 让 main 不跟随 forward
        _git(["checkout", "--detach", init_sha], cwd=project)

        # 步骤 2: 绕过 audit 直接 commit evil.py
        (project / "evil.py").write_text('import os\nos.system("rm -rf /")\n', encoding="utf-8")
        _git(["add", "evil.py"], cwd=project)
        _git(["commit", "-m", "add evil.py (bypassing audit)"], cwd=project)

        evil_sha = _git(["rev-parse", "HEAD"], cwd=project)[1].strip()
        main_sha = _git(["rev-parse", "main"], cwd=project)[1].strip()
        assert main_sha == init_sha, f"main 不应 advance: {main_sha} != {init_sha}"

        # 步骤 3: --base HEAD~1 --head HEAD → 看到 evil.py (FAIL)
        rc3, out3, _ = _run_cli("ci", "--root", str(project), "--base", "HEAD~1", "--head", "HEAD")
        assert rc3 == 1, f"--base HEAD~1 应检测到 evil.py 违规, rc={rc3}"

        # 步骤 4: --base main --head HEAD → 看 init..HEAD 全部,evil.py 违规
        rc4, out4, _ = _run_cli("ci", "--root", str(project), "--base", "main", "--head", "HEAD")
        assert rc4 == 1, f"--base main 应检测到 evil.py (init..HEAD), rc={rc4}, out={out4[-300:]}"
        assert "evil.py" in out4, f"输出应提到 evil.py, 实际: {out4[-500:]}"

        # 步骤 5: --base evil_sha --head HEAD → evil_sha..HEAD 无变更 → PASS
        rc5, out5, _ = _run_cli("ci", "--root", str(project), "--base", evil_sha, "--head", "HEAD")
        assert rc5 == 0, (
            f"--base evil_sha 应看到 0 violations, 但 rc={rc5}, out={out5[-500:]}"
        )


class TestCiNoInit:
    """未初始化目录应优雅处理"""

    def test_ci_no_init_fails_gracefully(self, tmp_path):
        """未 init 的目录 ci 应返回错误而非崩溃"""
        rc, out, err = _run_cli("ci", "--root", str(tmp_path))
        assert rc != 0, "未 init 应 fail"
        assert "未初始化" in out or "未初始化" in err or "REJECTED" in out or "REJECTED" in err

    def test_ci_dir_without_config_is_no_init_not_corrupted(self, tmp_path):
        """v0.7.16: .pandaone/ 存在但 config.json 缺失 → 报「未初始化」而非「损坏」

        CI 检出里正是这种形态：pandaone.jsonl 曾在 gitignore 生效前被提交，
        config.json 从未入库。旧实现报 "config.json 损坏 → 请 init --force-reset"，
        把「从未存在」说成「已损坏」，误导排查方向。
        """
        pandaone_dir = tmp_path / ".pandaone"
        pandaone_dir.mkdir()
        (pandaone_dir / "pandaone.jsonl").write_text("", encoding="utf-8")

        rc, out, err = _run_cli("ci", "--root", str(tmp_path))
        combined = out + err
        assert rc != 0, "缺少 config.json 应 fail"
        assert "未初始化" in combined or "not initialized" in combined.lower(), (
            f"应提示未初始化, 实际: {combined[-500:]}"
        )
        assert "损坏" not in combined and "corrupted" not in combined.lower(), (
            f"不应谎报 config.json 损坏, 实际: {combined[-500:]}"
        )


class TestCiGithubActionsYml:
    """GitHub Actions workflow 文件"""

    def test_workflow_file_exists(self):
        """应存在 .github/workflows/audit.yml"""
        yml_path = ROOT_DIR / ".github" / "workflows" / "audit.yml"
        assert yml_path.exists(), f"应存在 {yml_path}"

    def test_workflow_yaml_valid(self):
        """workflow YAML 应能解析（包含 name + on + jobs）"""
        import re
        yml_path = ROOT_DIR / ".github" / "workflows" / "audit.yml"
        if not yml_path.exists():
            pytest.skip("workflow yml not yet created")
        content = yml_path.read_text(encoding="utf-8")
        assert "name:" in content
        assert "on:" in content or "on " in content
        assert "jobs:" in content
        # 应安装 pandaone
        assert "pip install" in content or "pip install" in content.lower()
        # 应调用 pandaone ci
        assert "pandaone ci" in content

    def test_workflow_triggers_on_pull_request(self):
        """workflow 应在 pull_request 时触发"""
        yml_path = ROOT_DIR / ".github" / "workflows" / "audit.yml"
        if not yml_path.exists():
            pytest.skip("workflow yml not yet created")
        content = yml_path.read_text(encoding="utf-8")
        assert "pull_request" in content