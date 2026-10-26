# -*- coding: utf-8 -*-
"""
cmd_backup.py — `pandaone backup`：纯本地备份

对应外部建议书「建议 1.4」。

为什么需要
----------
Pandaone 的定位是"本地门禁"，但目前**本地备份能力是缺失的**：
git 有历史，但历史只在一个 `.git` 目录里，硬盘坏了就全没了。

设计：纯本地，不碰远程
--------------------
- `--output` 用 `git bundle` 生成**单文件**离线快照：
  拷走即可恢复，不需要装 gh、不需要登录 GitHub、不需要任何远程账号。
- `--mirror` 用 `git clone --mirror` 在**本地路径**建裸仓库镜像：
  裸仓库可以直接再 clone 回来，同样不需要远程。

远程（GitHub 等）**不默认启用**；用户后期自己配置好 remote 之后，
可以自行 `git bundle` / `git push` 组合使用，本命令不做这件事。
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path


def _t(key: str, **kw) -> str:
    try:
        from pandaone.i18n import t

        return t(key, **kw)
    except Exception:
        return key


COMMAND_NAME = "backup"


def add_parser(sub) -> None:
    p = sub.add_parser(
        COMMAND_NAME,
        help="纯本地备份（git bundle 单文件 / 本地裸仓库镜像，不碰远程）",
    )
    p.add_argument("--root", default=".", help="项目根目录路径（默认当前目录）")
    p.add_argument(
        "--output",
        default=None,
        metavar="PATH",
        help="bundle 输出路径（默认 ./<项目名>-<时间戳>.bundle）",
    )
    p.add_argument(
        "--mirror",
        default=None,
        metavar="DIR",
        help="额外创建本地裸仓库镜像目录（git clone --mirror 到本地路径）",
    )
    p.add_argument(
        "--no-bundle",
        action="store_true",
        help="不生成 bundle（只做镜像 / 只看状态）",
    )
    p.add_argument(
        "--status",
        action="store_true",
        help="只显示仓库与备份状态，不实际备份",
    )


def _default_output(root: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path.cwd() / f"{root.name or 'project'}-{stamp}.bundle"


def handler(args) -> int:
    root = Path(getattr(args, "root", ".") or ".").resolve()
    try:
        from pandaone import git_ops
    except ImportError as e:
        print(_t("backup_fail", err=str(e)))
        return 1

    print(_t("backup_header", root=str(root)))

    try:
        summary = git_ops.repo_summary(root)
    except Exception as e:
        print(_t("backup_fail", err=str(e)))
        return 1

    if not summary["is_repo"]:
        print(_t("backup_not_repo", root=str(root)))
        return 1

    print(
        _t(
            "backup_repo_info",
            head=summary["head"] or "-",
            commits=summary["commit_count"],
            remotes=", ".join(summary["remotes"]) or _t("backup_no_remote"),
        )
    )

    if getattr(args, "status", False):
        print(_t("backup_status_only"))
        return 0

    rc = 0
    made = []

    if not getattr(args, "no_bundle", False):
        out = Path(getattr(args, "output", None) or _default_output(root))
        try:
            bundle = git_ops.create_bundle(root, out)
            size_kb = bundle.stat().st_size / 1024.0
            print(_t("backup_bundle_ok", path=str(bundle), size=f"{size_kb:.1f} KB"))
            made.append(str(bundle))
        except git_ops.GitOpsError as e:
            print(_t("backup_bundle_fail", err=str(e)))
            rc = 1

    mirror_arg = getattr(args, "mirror", None)
    if mirror_arg:
        try:
            target = git_ops.create_mirror(root, mirror_arg)
            print(_t("backup_mirror_ok", path=str(target)))
            made.append(str(target))
        except git_ops.GitOpsError as e:
            print(_t("backup_mirror_fail", err=str(e)))
            rc = 1

    if not made and rc == 0:
        print(_t("backup_nothing"))
        return 0

    print(_t("backup_done", n=len(made)))
    print(_t("backup_local_only"))
    print(_t("backup_restore_hint"))
    return rc


if __name__ == "__main__":
    sys.exit(0)
