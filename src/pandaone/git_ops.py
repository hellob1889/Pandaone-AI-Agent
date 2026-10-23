# -*- coding: utf-8 -*-
"""
git_ops.py — 本地 git 操作层

被 `pandaone setup` / `pandaone init --with-git` / `pandaone backup` 复用。

设计约束（对应外部建议书的诉求）
--------------------------------
- **纯本地**：不设任何 remote、不推送任何东西、不需要 GitHub 账号。
  审计证据留在本机，符合"AI Agent 代码审计门禁"的定位。
- **不污染全局配置**：仓库级 user.name / user.email，绝不写 `git config --global`。
- **幂等**：重复执行不报错，能安全地在已初始化的仓库上再跑一次。
"""
from __future__ import annotations

import getpass
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path


class GitOpsError(Exception):
    """git 操作失败（已带可读原因）。"""


def git_exe() -> str | None:
    """找到可执行的 git。优先用 git_installer 的单一来源探测。"""
    try:
        from pandaone.git_installer import _find_git_executable

        p = _find_git_executable()
        if p:
            return p
    except Exception:
        pass
    return shutil.which("git")


@lru_cache(maxsize=1)
def git_support_path() -> str | None:
    """返回**含有 git-upload-pack / git-receive-pack** 的目录。

    为什么需要：
    Git for Windows 把 ``git.exe`` / ``git-upload-pack.exe`` /
    ``git-receive-pack.exe`` 全放在 ``cmd/`` 下，但 ``cmd/`` 常常**不在 PATH**
    （尤其当 git 是手动解压安装时）。
    ``git clone --mirror <本地路径>`` 会被 git 当成远程处理并调用
    git-upload-pack —— 不在 PATH 就报
    "git-upload-pack: command not found / fatal: Could not read from remote
    repository ... and the repository exists."。

    注意：``git --exec-path`` 指向的 ``mingw64/libexec/git-core`` 里
    **并没有** upload-pack，所以不能用 exec-path 解决。
    """
    exe = git_exe()
    if not exe:
        return None
    d = os.path.dirname(os.path.abspath(exe))
    for name in ("git-upload-pack.exe", "git-upload-pack"):
        if os.path.isfile(os.path.join(d, name)):
            return d
    return None


@lru_cache(maxsize=1)
def git_exec_path() -> str | None:
    """返回 git 的 exec-path（部分安装布局下 upload-pack 在这里）。"""
    exe = git_exe()
    if not exe:
        return None
    try:
        proc = subprocess.run(
            [exe, "--exec-path"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20
        )
        if proc.returncode == 0:
            p = proc.stdout.strip()
            return p or None
    except Exception:
        pass
    return None


def _git_env() -> dict:
    """构造跑 git 子进程用的环境变量。

    把 git-upload-pack 所在的目录补进 PATH —— 否则本地 clone --mirror 会失败。
    """
    env = dict(os.environ)
    # 避免交互式凭证提示把 CLI 卡死
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    env.setdefault("GIT_ASKPASS", "echo")
    current = env.get("PATH", "")
    extras = []
    for extra in (git_support_path(), git_exec_path()):
        if not extra:
            continue
        norm = extra.replace("/", os.sep).rstrip("\\/")
        if norm.lower() not in current.lower():
            extras.append(norm)
    if extras:
        env["PATH"] = os.pathsep.join(extras) + os.pathsep + current
    return env


def run_git(args, cwd: str | Path, check: bool = True, timeout: int = 120):
    """执行一条 git 命令。

    Returns:
        subprocess.CompletedProcess
    Raises:
        GitOpsError: check=True 且命令失败时
    """
    exe = git_exe()
    if not exe:
        raise GitOpsError("git executable not available (not installed or not in PATH)")
    try:
        proc = subprocess.run(
            [exe] + list(args),
            cwd=str(cwd),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout,
            env=_git_env(),
        )
    except subprocess.TimeoutExpired as e:
        raise GitOpsError(f"git command timed out: {' '.join(args)}") from e
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        tail = detail[-1] if detail else f"exit={proc.returncode}"
        raise GitOpsError(f"git {' '.join(args)} failed: {tail}")
    return proc


def is_repo(root: str | Path) -> bool:
    """root 是否已经是一个 git 仓库。"""
    try:
        p = run_git(["rev-parse", "--is-inside-work-tree"], cwd=root, check=False)
        return p.returncode == 0 and p.stdout.strip() == "true"
    except GitOpsError:
        return False


def has_commits(root: str | Path) -> bool:
    """仓库里是否已经有提交。"""
    try:
        p = run_git(["rev-parse", "--verify", "HEAD"], cwd=root, check=False)
        return p.returncode == 0
    except GitOpsError:
        return False


def _global_identity(root: str | Path) -> tuple[str | None, str | None]:
    """读取当前生效的 user.name / user.email（不含仓库级设置）。"""
    name = email = None
    try:
        p = run_git(["config", "--get", "user.name"], cwd=root, check=False)
        if p.returncode == 0 and p.stdout.strip():
            name = p.stdout.strip()
    except GitOpsError:
        pass
    try:
        p = run_git(["config", "--get", "user.email"], cwd=root, check=False)
        if p.returncode == 0 and p.stdout.strip():
            email = p.stdout.strip()
    except GitOpsError:
        pass
    return name, email


def default_identity() -> tuple[str, str]:
    """仓库级兜底身份：取本机用户名，绝不写全局配置。"""
    try:
        user = getpass.getuser()
    except Exception:
        user = "pandaone"
    user = user or "pandaone"
    return user, f"{user}@localhost"


def ensure_repo_identity(root: str | Path) -> tuple[bool, str]:
    """确保仓库有可用的提交身份。

    只在**用户没有配置任何身份**时，写入仓库级 user.name / user.email；
    已配置的用户身份一概不动，也绝不碰全局配置。

    Returns:
        (是否写入了兜底身份, 说明文本)
    """
    name, email = _global_identity(root)
    if name and email:
        return False, f"沿用现有身份: {name} <{email}>"
    d_name, d_email = default_identity()
    run_git(["config", "--local", "user.name", d_name], cwd=root)
    run_git(["config", "--local", "user.email", d_email], cwd=root)
    return True, f"已设置仓库级身份: {d_name} <{d_email}>（未改动全局配置，可自行修改）"


def init_repo(root: str | Path) -> tuple[bool, str]:
    """在 root 初始化 git 仓库（幂等）。

    Returns:
        (是否新建了仓库, 说明文本)
    """
    root = Path(root).resolve()
    if is_repo(root):
        return False, "已是 git 仓库，跳过 git init"
    run_git(["init"], cwd=root)
    run_git(["config", "--local", "core.autocrlf", "false"], cwd=root, check=False)
    return True, f"已初始化 git 仓库: {root}"


def baseline_commit(root: str | Path, message: str = "chore: Pandaone baseline") -> tuple[bool, str]:
    """做一次首次 baseline 提交（L2 自动回滚依赖它）。

    Returns:
        (是否真的提交了, 说明文本)
    """
    root = Path(root).resolve()
    if not is_repo(root):
        raise GitOpsError(f"{root} 不是 git 仓库，无法创建 baseline commit")
    if has_commits(root):
        return False, "仓库已有提交，跳过 baseline commit"
    # v0.7.23: 没有提交身份时 git commit 会直接失败
    # ("unable to auto-detect email address")。这里补一个仓库级兜底身份，
    # 绝不动全局配置。
    ensure_repo_identity(root)
    run_git(["add", "-A"], cwd=root)
    p = run_git(["diff", "--cached", "--quiet"], cwd=root, check=False)
    if p.returncode == 0:
        # 没有可提交内容（空仓库）
        return False, "没有可提交内容，跳过 baseline commit"
    run_git(["commit", "-m", message], cwd=root)
    return True, f"已创建 baseline commit: {message}"


def create_bundle(root: str | Path, output: str | Path) -> Path:
    """用 `git bundle` 生成**单文件**离线快照。

    - 纯本地：不需要 remote、不需要 GitHub 账号
    - 单文件：拷走即可（对应"硬盘坏了就全没了"的诉求）
    """
    root = Path(root).resolve()
    out = Path(output).expanduser().resolve()
    if not is_repo(root):
        raise GitOpsError(f"{root} 不是 git 仓库，无法生成 bundle")
    if not has_commits(root):
        raise GitOpsError("repository has no commits yet, cannot create bundle (run a baseline commit first)")
    out.parent.mkdir(parents=True, exist_ok=True)
    run_git(["bundle", "create", str(out), "--all"], cwd=root)
    if not out.is_file():
        raise GitOpsError(f"bundle was not created: {out}")
    return out


def _file_url(path: Path) -> str:
    """把本地路径转成 ``file://`` URL。

    为什么必须转：
    git 的 ``looks_like_path()`` 只认 ``/`` / ``~`` / ``.`` 开头，或
    "数字+冒号" 开头（即 POSIX 绝对路径与盘符数字路径）。
    Windows 绝对路径 ``C:\\Users\\...`` **不被识别为本地路径** →
    git 会走 smart transport 去调 git-upload-pack →
    "git-upload-pack: command not found / fatal: Could not read from remote
    repository"。

    加 ``file://`` 前缀可强制走 local transport（直接复制对象），
    既更快（不起子进程）也不依赖 upload-pack。
    """
    s = Path(path).resolve().as_posix()
    if not s.startswith("/"):
        s = "/" + s
    return "file://" + s


def _mirror_by_copy(root: Path, target: Path) -> Path:
    """回退方案：直接复制 ``.git`` 目录，得到一个**本地仓库**镜像。

    为什么需要回退：
    ``git clone --mirror`` 在 **Windows** 上必然走 smart transport
    （``looks_like_path()`` 不认 ``C:\\...`` 盘符路径，``file://`` 在
    Git for Windows 上同样走 smart transport），
    于是 git 会去调 ``git-upload-pack``。而 Git for Windows 的
    ``git-upload-pack.exe`` 在 ``cmd/`` 下 —— 该目录常常不在 PATH，
    且路径含中文时 MSYS 的 sh 也定位不到，最终报
    "git-upload-pack: command not found / fatal: Could not read from
    remote repository"。

    为什么复制成**普通仓库**而不是裸仓库：
    git 的 local clone 优化（``clone_local``）只对**普通仓库**生效；
    裸仓库源仍会走传输层 → 同样需要 git-upload-pack。
    复制成 ``<target>/.git/...`` 后，用户可以用
    ``git clone --local <target> <dir>`` 在任何平台零依赖地恢复 ✅

    同时复制 ``info/`` ``logs/`` ``refs/`` ``objects/`` 全套，
    恢复出来的仓库与源仓库等价（含全部 ref 与历史）。
    """
    src_git = root / ".git"
    if not src_git.is_dir():
        raise GitOpsError(f"cannot find .git directory in {root}")
    dest_git = target / ".git"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src_git, dest_git, symlinks=False)
    cfg = dest_git / "config"
    if cfg.is_file():
        # 清掉指向原工作区的绝对路径（复制后已无意义）
        run_git(
            ["config", "--file", str(cfg), "--unset", "core.worktree"],
            cwd=target,
            check=False,
        )
    return target


def create_mirror(root: str | Path, dest: str | Path) -> Path:
    """用本地**裸仓库**做镜像（`git clone --mirror` 到本地路径）。

    - 不需要任何远程账号
    - 裸仓库可直接再 clone 回来
    """
    root = Path(root).resolve()
    target = Path(dest).expanduser().resolve()
    if not is_repo(root):
        raise GitOpsError(f"{root} is not a git repository, cannot create mirror")
    if target.exists() and any(target.iterdir()):
        raise GitOpsError(
            f"target directory already exists and is not empty: {target}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        run_git(
            ["clone", "--mirror", _file_url(root), str(target)],
            cwd=root.parent,
        )
        return target
    except GitOpsError:
        # Windows 上 clone 本地路径会因缺 git-upload-pack 失败 -> 退回复制 .git
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        return _mirror_by_copy(root, target)


def repo_summary(root: str | Path) -> dict:
    """仓库概览（给 setup / backup 的输出用）。"""
    root = Path(root).resolve()
    info = {
        "root": str(root),
        "is_repo": False,
        "has_commits": False,
        "head": None,
        "commit_count": 0,
        "remotes": [],
    }
    try:
        if is_repo(root):
            info["is_repo"] = True
            info["has_commits"] = has_commits(root)
            p = run_git(["rev-parse", "--short", "HEAD"], cwd=root, check=False)
            if p.returncode == 0:
                info["head"] = p.stdout.strip()
            p = run_git(["rev-list", "--count", "HEAD"], cwd=root, check=False)
            if p.returncode == 0:
                try:
                    info["commit_count"] = int(p.stdout.strip())
                except ValueError:
                    pass
            p = run_git(["remote", "-v"], cwd=root, check=False)
            if p.returncode == 0:
                info["remotes"] = [
                    line.strip() for line in p.stdout.splitlines() if line.strip()
                ]
    except GitOpsError:
        pass
    return info
