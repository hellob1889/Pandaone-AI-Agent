# cli.py chunk 5/6: lines 1612-2068
def cmd_serve(args):
    """启动 Web 仪表盘。"""
    from pandaone.pandaone_serve import run_blocking
    root = Path(args.root).resolve()
    config_path = root / ".pandaone" / "config.json"
    if not config_path.exists():
        print(t("err_write_root_not_init", root=root))
        return 1
    port = getattr(args, "port", 8765) or 8765
    return run_blocking(root, port=port)


def _load_install_hook_module():
    """加载 install_hook 模块，冻结形态下必须从磁盘按路径加载。

    为什么不能用 `from pandaone.install_hook import ...`:
      冻结包的模块表（PYZ）里**没有** pandaone.install_hook —— 它只作为
      "数据文件"被整棵树拷进 _internal/pandaone/（见 build_pyinstaller.py 的
      package_data_args()），静态 import 会直接 ImportError。

    为什么不能用 `sys.executable -m pandaone.install_hook`:
      冻结形态下 sys.executable 就是 pandaone.exe 本身，没有 "-m 模块执行"
      语义 —— argparse 会把 "pandaone.install_hook" 当成子命令名，于是报
      "invalid choice: 'pandaone.install_hook'"。
      （真机装 0.7.32.0 时实测到的真 bug；cmd_setup / cmd_upgrade /
      pandaone_mcp 早就有 frozen 感知，只有这条漏了。）

    所以：从 _internal/pandaone/install_hook.py 按文件路径加载。这样模块内的
    ROOT = Path(__file__).parent / "templates" 才会指向**冻结包内**那份模板，
    而不是源码树里的。
    """
    import importlib.util

    # 冻结形态：install_hook.py 在 exe 同级的 _internal/pandaone/ 下
    candidates = []
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
        candidates.append(base / "_internal" / "pandaone" / "install_hook.py")
    # 源码形态：模块在包里，按包目录定位（install_hook.py 与 cli.py 同级）
    #
    # v0.7.34.0 fix: 原来写的是 parent.parent —— 那是**假设** __file__ 仍是
    #   cli_chunks/part_005.py 自己的路径。但 cli.py 加载完 chunk 后会把
    #   __file__ 恢复成 cli.py 的路径（见 cli.py 里的 _orig_file 还原逻辑），
    #   运行期取到的其实是 <repo>/src/pandaone/cli.py，
    #   parent.parent 解析成 <repo>/src → <repo>/src/install_hook.py 不存在
    #   → **源码形态下这个函数永远返回 None**。
    #   冻结形态靠第一个候选（exe 同级）兜住了，所以这个 bug 一直没暴露；
    #   但 doctor 的 L3 真检要用它（安装命令在当前形态可加载），
    #   不修的话源码形态下 L3 会永远误报 FAIL。
    # 两个候选都保留: chunk 命名空间里 __file__ 是 part_005.py（parent.parent 对），
    # cli 命名空间里 __file__ 是 cli.py（parent 对）—— 两个都要能找到。
    _here = Path(__file__).resolve().parent
    candidates.append(_here / "install_hook.py")
    candidates.append(_here.parent / "install_hook.py")

    for path in candidates:
        try:
            if not path.is_file():
                continue
            spec = importlib.util.spec_from_file_location("pandaone.install_hook", path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        except Exception:
            continue
    return None


def cmd_install_hook(args):
    """安装/卸载 pre-commit hook。委托给 install_hook.py"""
    import subprocess
    if getattr(sys, "frozen", False):
        # 冻结形态：进程内直接调用（sys.executable -m 在 exe 形态下无模块执行语义）
        module = _load_install_hook_module()
        if module is None:
            print(t("err_hook_module_missing"), file=sys.stderr)
            return 1
        root = Path(args.root).resolve()
        try:
            if getattr(args, "uninstall", False):
                return module.uninstall_hook(root)
            return module.install_hook(root)
        except Exception as e:
            print(t("err_hook_install", err=str(e)), file=sys.stderr)
            return 1
    cmd = [sys.executable, "-m", "pandaone.install_hook", "--root", args.root]
    if getattr(args, "uninstall", False):
        cmd.append("--uninstall")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=10)
        print(r.stdout, end="")
        if r.stderr:
            print(r.stderr, end="", file=sys.stderr)
        return r.returncode
    except subprocess.TimeoutExpired:
        return 1


def cmd_install_git(args):
    """探测/安装 git。"""
    import shutil
    print(t("git_probe_check"))
    existing = shutil.which("git")
    if existing:
        print(t("git_probe_found", path=existing))
        return 0
    # Bug #40 fix (v0.7.10): 不再硬编码作者机器路径 `D:\软件\Git\cmd`，
    # 统一从 git_installer._windows_candidate_dirs() 派生候选目录
    # (基于 %ProgramFiles% / %LOCALAPPDATA% / 注册表 InstallPath)
    if os.name == "nt":
        try:
            from pandaone.git_installer import _windows_candidate_dirs
            cands = _windows_candidate_dirs()
        except ImportError:
            cands = [
                r"C:\Program Files\Git\cmd",
                r"C:\Program Files (x86)\Git\cmd",
                r"C:\Program Files\Git\bin",
                r"C:\Git\cmd",
            ]
    else:
        cands = []
    for cand in cands:
        git_exe = Path(cand, "git.exe")
        if not git_exe.exists():
            continue
        # v0.7.22 P1-1 fix: 候选目录命中后再用 _can_run_git() 验证真能执行 ——
        # 0 字节占位文件 / 被杀软隔离的 git.exe 之前会被误判成"已安装",
        # 然后 L2/L3 静默失效, 用户以为防护装好了其实没有。
        try:
            from pandaone.git_installer import _can_run_git
            if not _can_run_git(str(git_exe)):
                continue
        except ImportError:
            pass
        print(t("git_probe_found", path=str(git_exe)))
        return 0
    print(t("git_not_installed"))
    # v0.7.22 P1-1 fix: 接上 git_installer —— 之前 cmd_install_git 只探测不安装,
    # 自己写的 _install_windows()(winget → choco) 是死代码, 跑 install-git 永远装不上。
    # 同时让 --probe-only 真正生效(之前注册了这个参数却从没被读过)。
    if getattr(args, "probe_only", False):
        return 1
    if getattr(args, "auto_download", False):
        return _download_portable_git()
    try:
        from pandaone.git_installer import install as _git_install, GitInstallError
    except ImportError:
        return 1
    try:
        result = _git_install()
    except GitInstallError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        try:
            from pandaone.git_installer import get_install_hint
            print(get_install_hint())
        except ImportError:
            pass
        return 1
    print(t("git_installed", path=result.path))
    return 0


def _download_portable_git():
    """下载 PortableGit zip 并解压。"""
    import urllib.request
    import zipfile
    version = "2.47.1"
    url = f"https://github.com/git-for-windows/git/releases/download/v{version}.windows.1/PortableGit-{version}-64-bit.zip"
    target = ROOT / "git"
    target.mkdir(parents=True, exist_ok=True)
    zip_path = target / "git.zip"
    print(t("git_downloading", url=url))
    try:
        urllib.request.urlretrieve(url, zip_path, timeout=30)  # v0.7.19 fix: 加 timeout 避免下载挂死
    except Exception as e:
        print(t("git_download_failed", err=e))
        return 1
    print(t("git_extracting"))
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(target)
    except Exception as e:
        print(t("git_extract_failed", err=e))
        return 1
    finally:
        zip_path.unlink(missing_ok=True)
    git_exe = target / "cmd" / "git.exe"
    if git_exe.exists():
        print()
        print(t("git_installed", path=git_exe))
        return 0
    print(t("git_install_failed"))
    return 1


def cmd_watch(args):
    """启动 watchdog。"""
    import subprocess
    root = Path(args.root).resolve()
    pandaone_dir = root / ".pandaone"
    if not pandaone_dir.exists():
        print(t("_watch_no_init", root=root))
        return 1
    if getattr(args, "daemon", False):
        log_path = pandaone_dir / "watchdog.log"
        log_file = open(log_path, "ab")
        kwargs = {"stdout": log_file, "stderr": log_file, "stdin": subprocess.DEVNULL, "close_fds": True}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).resolve().parent
            watchdog_exe = exe_dir / "pandaone_guard.exe"
            if not watchdog_exe.exists():
                return 1
            cmd = [str(watchdog_exe), "--root", str(root), "--daemon"]
        else:
            cmd = [sys.executable, "-m", "pandaone_guard", "--root", str(root), "--daemon"]
        p = subprocess.Popen(cmd, env={**os.environ, "PYTHONUNBUFFERED": "1"}, **kwargs)
        pid_path = pandaone_dir / ".watchdog_pid"
        # v0.7.22 P1-4 fix: 之前 Popen 完不看进程活没活, 无条件 print "已在后台启动"
        # 并 return 0 —— 用户实测遇到过"报告启动成功但查不到进程"。
        # 现在: 子进程提前退出, 或等待后 pid 文件仍未生成, 都算失败并明确报错。
        for _ in range(50):          # 最多等 5s 给子进程写 pid 文件
            if pid_path.exists():
                break
            if p.poll() is not None:  # 子进程已退出 → 启动失败
                break
            time.sleep(0.1)
        if p.poll() is not None:
            print(t("watch_daemon_failed"), file=sys.stderr)
            print(f"  exit code: {p.returncode}", file=sys.stderr)
            log_file_path = pandaone_dir / "watchdog.log"
            if log_file_path.exists():
                try:
                    tail = log_file_path.read_text(
                        encoding="utf-8", errors="replace"
                    ).splitlines()[-10:]
                    for line in tail:
                        print(f"  {line}", file=sys.stderr)
                except Exception:
                    pass
            return 1
        if not pid_path.exists():
            print(t("watch_daemon_failed"), file=sys.stderr)
            print(t("watch_daemon_no_pid"), file=sys.stderr)
            return 1
        print(t("watch_daemon_started"))
        return 0
    sys.path.insert(0, str(ROOT))
    try:
        from pandaone_guard import run_watchdog
        run_watchdog(root, daemon=False)
    except ImportError as e:
        print(t("hook_import_err", err=e))
        return 1
    return 0


def cmd_ci(args):
    """Phase 7 — GitHub Actions CI 验证。"""
    import hashlib as _hl
    import json as _json
    import subprocess
    import shutil as _sh
    root = Path(args.root).resolve()
    pandaone_dir = root / ".pandaone"
    git_exe_path = _resolve_git_exe()
    GIT = git_exe_path
    def _git_run(*args, timeout=5):
        try:
            return subprocess.run([GIT] + list(args), cwd=str(root), capture_output=True,
                                  text=True, encoding="utf-8", errors="replace",
                                  timeout=timeout)
        except subprocess.TimeoutExpired:
            return None
    if not pandaone_dir.exists():
        print(t("ci_reject_no_init", root=root))
        return 1
    config_path = pandaone_dir / "config.json"
    try:
        config = _json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        # v0.7.16 fix: 目录存在但 config.json 缺失 ≠ 文件损坏。
        # 典型场景：CI 检出里 .pandaone/ 只有曾经被提交过的 pandaone.jsonl，
        # config.json 从未入库（gitignore）。旧实现报 "config.json corrupted →
        # 请运行 init --force-reset"，误导用户去重置一个本就不存在的配置。
        print(t("ci_reject_no_init", root=root))
        return 1
    except (_json.JSONDecodeError, OSError) as e:
        print(t("err_config_corrupted", err=e))
        return 1
    text_exts = set(config.get("protected_extensions", [".py"]))
    binary_exts = set(config.get("binary_protected_extensions", []))
    base = args.base or "main"
    head = args.head or "HEAD"
    try:
        r = _git_run("rev-parse", "--is-inside-work-tree")
        if r is None or r.returncode != 0:
            print(t("ci_reject_no_git_repo", root=root))
            return 1
    except FileNotFoundError:
        print(t("ci_reject_no_git", git=GIT))
        return 1
    def _resolve_ref(ref):
        r = _git_run("rev-parse", "--verify", ref)
        return r is not None and r.returncode == 0
    base_resolved = False
    # PR #33 fix (baseline order): 用户的 base 必须优先于 HEAD~1 fallback。
    # 之前 candidates[0] = "HEAD~1" 永远存在,导致即使传 --base main 也被 HEAD~1 顶替,
    # --base 参数实际失效。改成 base → origin/base → HEAD~1 → main/master,这样:
    #   1) 用户传 --base main  → 直接用 main(尊重显式意图)
    #   2) --base NONEXISTENT  → HEAD~1 fallback(原行为保留)
    #   3) 没传 base(默认 main) → main(原行为保留)
    candidates = [base, f"origin/{base}", "HEAD~1", "main", "master", "origin/main", "origin/master"]
    for ref in candidates:
        if _resolve_ref(ref):
            base = ref
            base_resolved = True
            break
    if not base_resolved:
        r_any = _git_run("rev-list", "-n", "1", "--all")
        if r_any is None or r_any.returncode != 0 or not r_any.stdout.strip():
            print(t("ci_pass_empty"))
            return 0
        print(t("ci_reject_no_baseline", base=base))
        return 1
    diff_range = f"{base}...{head}" if head == "HEAD" else f"{base}..{head}"
    r = _git_run("diff", "--name-only", diff_range, timeout=10)
    if r is None or r.returncode != 0:
        err_msg = r.stderr.strip() if r is not None else "(timeout)"
        print(t("ci_reject_diff_fail", err=err_msg))
        return 1
    changed_files = [f.strip().replace("\\", "/") for f in r.stdout.splitlines() if f.strip()]
    audit_records = []
    audit_path = pandaone_dir / "pandaone.jsonl"
    if audit_path.exists():
        for line in audit_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    audit_records.append(_json.loads(line))
                except _json.JSONDecodeError:
                    continue
    approved_files = {rec.get("file", "").replace("\\", "/") for rec in audit_records if rec.get("status") == "APPROVED"}
    snapshots = {}
    snap_path = pandaone_dir / "binary_snapshots.json"
    if snap_path.exists():
        try:
            snapshots = _json.loads(snap_path.read_text(encoding="utf-8"))
        except _json.JSONDecodeError:
            pass
    violations = []
    for rel in changed_files:
        ext = Path(rel).suffix
        if ext in binary_exts:
            fp = root / rel
            if not fp.exists():
                continue
            actual_sha = _hl.sha256(fp.read_bytes()).hexdigest()
            expected_sha = snapshots.get(rel)
            if expected_sha != actual_sha:
                violations.append({"file": rel, "type": "binary", "reason": "SHA256 mismatch"})
        elif ext in text_exts:
            if rel not in approved_files:
                violations.append({"file": rel, "type": "text", "reason": "no APPROVED audit"})
    print("=" * 64)
    print(t("ci_header", root=root))
    print(t("ci_baseline", base=base, head=head))
    print(t("ci_changed_n", n=len(changed_files)))
    print("=" * 64)
    if not violations:
        print(t("ci_pass_all"))
        return 0
    print(f"\n{t('ci_fail_n', n=len(violations))}\n")
    for v in violations:
        print(f"  {v['file']}: {v['reason']}")
    return 1
