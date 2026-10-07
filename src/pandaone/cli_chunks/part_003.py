# cli.py chunk 3/6: lines 729-1201
def _iter_protected_files(root: Path, config: dict) -> list[Path]:
    """
    Bug #2 fix: 共享 helper — 列出项目根目录下所有受保护扩展名的文件。

    被 cmd_status（仪表盘）、_apply_readonly（lock/unlock）、cmd_ci 等共用。
    之前 cmd_status 只看 *.py，忽略了 18 种其它受保护扩展名（.json, .yaml, .env 等），
    导致 status 报告的"锁定文件数"严重低估，用户看不到 L1 锁的真实覆盖。

    参数：
      - root: 项目根目录
      - config: 项目配置 dict（含 protected_extensions + exclude_patterns）

    返回：受保护文件路径列表（排除 __pycache__、.git、exclude_patterns 等）
    """
    import fnmatch

    protected_exts = set(config.get("protected_extensions", [".py"]))
    exclude_patterns = config.get("exclude_patterns", [])

    files = []
    seen = set()
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p in seen:
            continue
        if _effective_suffix(p) not in protected_exts:
            continue
        seen.add(p)

        # 排除判断
        try:
            rel = p.relative_to(root)
        except ValueError:
            continue
        skip = False
        for pat in exclude_patterns:
            if any(fnmatch.fnmatch(part, pat) for part in rel.parts):
                skip = True
                break
            if fnmatch.fnmatch(rel.name, pat):
                skip = True
                break
        if skip:
            continue

        files.append(p)
    return files


def _apply_readonly(args, readonly: bool) -> int:
    """
    共享的锁/解锁函数。
    Phase 4.6: 遍历 config.json 中所有 protected_extensions（不再只看 .py）。
    跨平台：Windows 用 os.chmod 设只读属性；Linux/Mac 用 0o444。
    排除：__pycache__、*.pyc、_tmp_*.py、_fix*.py

    Bug #28 (方案 A): readonly=True 且未 init 时自动调用 cmd_init
      - 目的：首次使用"右击 → Lock"一键到位
      - 反向控制：args.no_auto_init=True 跳过自动 init
      - 对抗式审查：auto_init 只用于 lock，不用于 unlock
    """
    import json
    import os
    import stat

    root = Path(args.root).resolve()
    config_path = root / ".pandaone" / "config.json"

    # 检查是否 init 过
    if not config_path.exists():
        # Bug #28 (方案 A): lock 时未 init → 自动调 cmd_init（除非显式 --no-auto-init）
        if readonly and not getattr(args, "no_auto_init", False):
            print(t("info_lock_auto_init", root=root))
            # 构造 init 用的 args（用同 root，保留其他 init 默认值）
            import argparse
            init_args = argparse.Namespace(
                root=str(root),
                ext=None,            # 用默认 17 种扩展名
                no_binary=False,     # 启用二进制保护（默认行为）
            )
            rc = cmd_init(init_args)
            if rc != 0:
                return rc
            # init 成功 → 继续 lock（不返回）
        else:
            print(t("err_write_root_not_init", root=root))
            return 1

    # 读取配置（含 protected_extensions + exclude_patterns）
    # Bug #16 fix
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(t("err_config_corrupted", err=e))
        return 1
    protected_extensions = config.get("protected_extensions", [".py"])

    count = 0
    # v0.7.16 fix: unlock 不再一律加 group/other 写位（444 → 666 world-writable）。
    #   lock 会清除三种写位，原始 mode 就此丢失；解锁时若无记录只能猜。
    #   方案：lock 时把每个文件的原始 mode 记入 .pandaone/lock_modes.json，
    #         unlock 时精确还原；无记录（旧版本 lock / 手工 chmod）时退化为
    #         "仅恢复属主写位、不加 group/other 写位"（默认 644，不 world-writable）。
    modes_path = root / ".pandaone" / "lock_modes.json"
    saved_modes: dict = {}
    if not readonly and modes_path.exists():
        try:
            saved_modes = json.loads(modes_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            saved_modes = {}

    # Bug #2 fix: 用 _iter_protected_files 共享 helper（避免与 cmd_status 行为漂移）
    for target_file in _iter_protected_files(root, config):
        try:
            current_mode = target_file.stat().st_mode
            rel_key = target_file.relative_to(root).as_posix()
            if readonly:
                # 记录原始 mode 后再上锁（仅记录尚未上锁的文件，避免二次 lock 覆盖成 444）
                if current_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
                    saved_modes[rel_key] = stat.S_IMODE(current_mode)
                new_mode = current_mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH
            else:
                if rel_key in saved_modes:
                    # 精确还原锁定前的 mode
                    new_mode = (current_mode & ~0o777) | int(saved_modes[rel_key])
                else:
                    # 无记录：只恢复属主写位，绝不补 group/other 写位
                    new_mode = (current_mode | stat.S_IWUSR) & ~stat.S_IWGRP & ~stat.S_IWOTH
            os.chmod(target_file, new_mode)
            count += 1
        except OSError as e:
            print(t("warn_lock_failed", file=target_file, err=e))

    # 持久化 mode 记录（lock 时写入；unlock 后清理，避免陈旧记录影响后续）
    try:
        if readonly:
            modes_path.write_text(
                json.dumps(saved_modes, ensure_ascii=False), encoding="utf-8"
            )
        elif modes_path.exists():
            modes_path.unlink()
    except OSError:
        pass

    action = "锁定" if readonly else "解锁"
    ext_list = ", ".join(protected_extensions)
    if readonly:
        print(t("ok_locked_n", n=count, exts=ext_list))
    else:
        print(t("ok_unlocked_n", n=count, exts=ext_list))

    try:
        from pandaone.desktop_icon import apply_desktop_icon, remove_desktop_icon
        if readonly:
            ok, msg = apply_desktop_icon(root, "locked")
        else:
            ok, msg = remove_desktop_icon(root)
        if msg and "[SKIP]" not in msg:
            print(msg)
    except ImportError:
        pass
    except Exception as e:
        print("[WARN] icon toggle failed (lock/unlock still ok): " + str(e))

    return 0


def _resolve_git_exe() -> str:
    """
    Bug #21 fix: 统一 git 可执行解析逻辑，所有 git 调用共享。

    之前 doctor (scripts/doctor.py) 用 shutil.which + Windows 候选目录回退，
    但 write/ci 直接 subprocess.run(["git", ...])。边缘场景下行为不一致。

    Bug #40 fix (v0.7.10): 移除所有 `D:\\软件\\Git\\cmd` 等作者机器硬编码路径。
    改为调用 git_installer._windows_candidate_dirs() 单一来源
    (基于 %ProgramFiles% / %LOCALAPPDATA% / 注册表 InstallPath)。

    策略：与 doctor 相同的"PATH 优先 + Windows 候选回退"算法。
    返回值是绝对路径（如果找到）或 "git"（fallback，让 subprocess 自己找）。
    """
    import shutil as _sh
    git_path = _sh.which("git")
    if git_path:
        return git_path
    # Windows 常见安装路径（与 doctor.py + git_installer.py 共用）
    if os.name == "nt":
        try:
            from pandaone.git_installer import _windows_candidate_dirs
            for c in _windows_candidate_dirs():
                p = Path(c, "git.exe")
                if p.exists():
                    # 同时把候选目录加入当前进程 PATH，避免后续 subprocess 找不到
                    os.environ["PATH"] = str(Path(c)) + os.pathsep + os.environ.get("PATH", "")
                    return str(p)
        except ImportError:
            # git_installer 不在时退到最小硬编码候选（仅标准位置，无作者路径）
            for c in [r"C:\Program Files\Git\cmd", r"C:\Program Files (x86)\Git\cmd",
                      r"C:\Program Files\Git\bin", r"C:\Git\cmd"]:
                p = Path(c, "git.exe")
                if p.exists():
                    os.environ["PATH"] = str(Path(c)) + os.pathsep + os.environ.get("PATH", "")
                    return str(p)
    return "git"  # 让 subprocess 自己解析（最佳努力 fallback）


def cmd_write(args):
    """
    审计写入（核心命令）：
      1. 水质检测（reason/problem/approach 必填且满足长度）
      2. 设审计令牌
      3. 解锁目标文件
      4. 写入（字符串替换 / 整文件）
      5. 重新锁定
      6. 清审计令牌
      7. git add + commit
      8. 写审计记录
    """
    import datetime as dt
    import json
    import os
    import stat
    import subprocess
    import uuid

    root = Path(args.root).resolve()
    config_path = root / ".pandaone" / "config.json"

    # 检查 init
    if not config_path.exists():
        print(t("err_write_rejected", root=root))
        return 1

    # Bug #16 fix
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(t("err_config_corrupted", err=e))
        return 1

    # === [1] 水质检测 ===
    reason = args.reason.strip()
    problem = args.problem.strip()
    approach = args.approach.strip()
    min_reason = config.get("min_reason_length", 5)
    min_problem = config.get("min_problem_length", 10)
    min_approach = config.get("min_approach_length", 10)

    reject_reason = None
    if not reason:
        reject_reason = t("write_reject_empty_reason")
    # Bug #9 fix: 用 _info_length() 计算 unicode 宽度，1 中文字 = 2 宽度单位，
    # 避免"测试"（2 中文字 = 4 宽度）被 5 字符阈值误伤（修复前 len=2 < 5）
    elif _info_length(reason) < min_reason:
        reject_reason = f"reason 长度不足（< {min_reason} 宽度单位，含 CJK 字符按 2 计）"
    elif not problem:
        reject_reason = t("write_reject_empty_problem")
    # Bug #10 fix: 同上，problem/approach 也用 _info_length()
    elif _info_length(problem) < min_problem:
        reject_reason = f"problem 长度不足（< {min_problem} 宽度单位，含 CJK 字符按 2 计）"
    elif not approach:
        reject_reason = t("write_reject_empty_approach")
    elif _info_length(approach) < min_approach:
        reject_reason = f"approach 长度不足（< {min_approach} 宽度单位，含 CJK 字符按 2 计）"

    target_rel = args.file
    target = root / target_rel

    # Phase 5: 检测是文本还是二进制文件（Phase 4.6+ 使用 _effective_suffix 处理隐藏文件）
    text_exts = config.get("protected_extensions", [".py"])
    binary_exts = config.get("binary_protected_extensions", [])
    target_eff_suffix = _effective_suffix(target)
    is_binary = target_eff_suffix in binary_exts

    # 检查目标文件存在 + 后缀受保护
    # v0.7.15: 允许通过审计通道创建新文件（MCP/Agent 核心场景）。
    #   之前新文件一律 REJECTED，逼 Agent 绕过审计直接写文件，门禁形同虚设。
    #   现在新建必须满足：扩展名在保护范围内 + 提供完整内容（--content /
    #   --content-base64 / --from-file），审计记录 status=APPROVED + action=create。
    has_content_payload = bool(args.content or args.content_base64 or args.from_file)
    is_new_file = not target.exists()
    if is_new_file:
        if not has_content_payload:
            reject_reason = (
                f"目标文件不存在: {target_rel}"
                f"（新建文件需提供 --content / --content-base64 / --from-file）"
            )
        elif is_binary and target_eff_suffix not in binary_exts:
            reject_reason = f"只允许创建二进制保护范围({binary_exts})内的文件"
        elif not is_binary and target_eff_suffix not in text_exts:
            reject_reason = f"只允许创建文本保护范围({text_exts})内的文件"
        elif args.old:
            reject_reason = "新文件不支持 --old/--new（无原文可替换），请用 --content"
    elif not is_binary and target_eff_suffix not in text_exts:
        reject_reason = f"只允许修改文本({text_exts})或二进制({binary_exts})保护范围内的文件"

    # 二进制文件不接受 --old/--new（语义化替换对二进制无意义）
    if not reject_reason and is_binary and (args.old or args.new):
        reject_reason = t("write_reject_binary_old_new")

    # === Bug #12 v2: L1 文件锁 ReadOnly 前置检查 ===
    # 默认拒绝修改 OS ReadOnly 文件（pandaone lock 设的）。仅 --force-write 才放行。
    # 对抗式审查：如果允许 write 默认解锁，恶意 Agent 可绕过用户意图。
    # v0.7.15 fix: 改用 mode 位检查而非 os.access()。
    #   os.access() 以 real uid 判断，root（容器内 Agent 的常见环境）对 444
    #   文件也返回可写，导致 L1 锁对 root 完全失效。mode 位检查不受影响。
    if not reject_reason and target.exists():
        _locked = not (target.stat().st_mode & stat.S_IWUSR)
        if _locked and not getattr(args, "force_write", False):
            reject_reason = t("write_reject_readonly_need_force", file=target_rel)

    if reject_reason:
        # 写拒绝记录
        audit_path = root / ".pandaone" / "pandaone.jsonl"
        record = {
            "id": f"audit_{uuid.uuid4().hex[:8]}",
            "timestamp": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "REJECTED",
            "file": target_rel,
            "agent": getattr(args, "agent", "user:anonymous"),
            "rejection_reason": reject_reason,
            "attempted_reason": args.reason,
            "attempted_problem": args.problem,
            "attempted_approach": args.approach,
            "files_changed": [],
        }
        with audit_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        print(f'[REJECTED] {{"status":"REJECTED","reason":"{reject_reason}"}}')
        return 1

    # === [2] 设审计令牌 ===
    token_path = root / ".pandaone" / ".audit_token"
    audit_path = root / ".pandaone" / "pandaone.jsonl"  # 提前定义给后续 git add 用
    token_path.write_text(str(uuid.uuid4()), encoding="utf-8")

    # === [3] 解锁目标文件 ===
    # v0.7.15: 新建文件没有原始 mode，跳过解锁/恢复（也无需恢复锁定状态）。
    if is_new_file:
        mode = None
        target.parent.mkdir(parents=True, exist_ok=True)
    else:
        mode = target.stat().st_mode
        # v0.7.16: 只加属主写位（旧实现同时开 group/other → 写入期间文件 world-writable）。
        #   finally 会把 mode 原样还原，这里只需让本次写入通行；
        #   非属主且非 root 的进程本就无法 chmod/chmod 后写入，多开写位毫无意义。
        writable_mode = mode | stat.S_IWUSR
        os.chmod(target, writable_mode)

    # 准备 step 4→5 的 try/finally 块：
    # Bug #12 fix: write_text/write_bytes 在隐藏/系统文件上会抛 PermissionError，
    # 旧代码没有 try/except，导致文件 mode 永久变为 writable，绕过文件锁。
    # 用 try/finally 确保无论写入成功或失败都恢复原始 mode。

    # === [4] 写入（Phase 5: 文本 vs 二进制分支）===
    # Bug #12 fix: 整个 step 4 包在 try/finally 中，确保文件 mode 始终恢复。
    # 任何 write_text/write_bytes 抛错（hidden/system 文件、磁盘满等），
    # finally 块都会恢复原始 mode —— 审计门禁不能因 IO 错误绕过文件锁。
    write_error = None
    try:
        if is_binary:
            # 二进制文件：必须用 --from-file 或 --content-base64
            import base64 as b64
            if args.from_file:
                src = Path(args.from_file)
                if not src.exists():
                    raise FileNotFoundError(f"from-file not found: {args.from_file}")
                new_bytes = src.read_bytes()
            elif args.content_base64:
                try:
                    new_bytes = b64.b64decode(args.content_base64)
                except Exception as e:
                    raise ValueError(f"base64 decode error: {e}") from e
            else:
                raise ValueError("binary file must use --from-file or --content-base64")
            target.write_bytes(new_bytes)
            # Phase 5: 更新 SHA256 快照
            import hashlib
            new_sha = hashlib.sha256(target.read_bytes()).hexdigest()
            _update_binary_snapshot(root, target_rel, new_sha)
        elif args.content:
            # 文本整文件模式
            # v0.7.15: 新建文件没有原文，original_content 置空
            original_content = target.read_text(encoding="utf-8") if target.exists() else ""
            new_content = args.content
            target.write_text(new_content, encoding="utf-8")
        elif args.old:
            # 文本字符串替换模式
            original_content = target.read_text(encoding="utf-8")
            if args.old not in original_content:
                # 用专用异常类型让外层识别为业务拒绝（不是 IO 错误）
                raise _OldNotFoundError(args.old[:30])
            new_content = original_content.replace(args.old, args.new, 1)
            target.write_text(new_content, encoding="utf-8")
        else:
            raise ValueError("must specify --old/--new or --content")
    except _OldNotFoundError as e:
        # 业务拒绝（--old 不在文件中）：记录 audit + 返回 REJECTED
        # finally 块负责恢复 mode
        write_error = ("REJECTED", f"--old 字符串不在文件中: {e}...")
    except Exception as e:
        # IO 错误或其他异常：记录 audit + 返回 REJECTED
        write_error = ("REJECTED", f"写入失败: {type(e).__name__}: {e}")
    finally:
        # === [5] 重新锁定（恢复原始 mode）===
        # Bug #12 fix: 不论 write 成功或失败，都恢复原始 mode。
        # 直接用 step 3 保存的 `mode`（而不是再算 readonly_mode），
        # 这样能完整恢复 hidden/system/archive 等所有 file attributes。
        # v0.7.15: 新建文件（mode=None）无原始 mode 可恢复，跳过。
        if mode is not None:
            try:
                os.chmod(target, mode)
            except Exception as chmod_err:
                # 如果 chmod 失败（极少见，例如文件被另一进程占用），
                # 必须明确告知用户 — 这是审计安全 fallback
                print(f'[WARN] failed to restore file mode for {target_rel}: {chmod_err}')
                if write_error is None:
                    write_error = ("REJECTED", f"无法恢复文件锁定状态: {chmod_err}")

    if write_error is not None:
        # 记录 REJECTED audit
        status, reason = write_error
        record = {
            "id": f"audit_{uuid.uuid4().hex[:8]}",
            "timestamp": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "REJECTED",
            "file": target_rel,
            "agent": getattr(args, "agent", "user:anonymous"),
            "rejection_reason": reason,
            "attempted_reason": args.reason,
            "attempted_problem": args.problem,
            "attempted_approach": args.approach,
            "files_changed": [],
        }
        with audit_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        token_path.unlink(missing_ok=True)
        print(f'[REJECTED] {{"status":"REJECTED","reason":"{reason}"}}')
        return 1

    # === [6] 清审计令牌 ===
    token_path.unlink(missing_ok=True)

    # === [7] 写审计记录 ===
    audit_id = f"audit_{uuid.uuid4().hex[:8]}"
    DIFF_MAX = 500
    old_content_diff = ""
    new_content_diff = ""
    if not is_binary:
        try:
            full_new = target.read_text(encoding="utf-8")
            if args.old:
                full_old_reconstructed = full_new.replace(args.new, args.old, 1) if args.new in full_new else full_new
            else:
                full_old_reconstructed = ""
            old_content_diff = full_old_reconstructed if len(full_old_reconstructed) <= DIFF_MAX else full_old_reconstructed[:DIFF_MAX] + "\n... (truncated)"
            new_content_diff = full_new if len(full_new) <= DIFF_MAX else full_new[:DIFF_MAX] + "\n... (truncated)"
        except Exception:
            old_content_diff = ""
            new_content_diff = ""
    record = {
        "id": audit_id,
        "timestamp": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "APPROVED",
        "action": "create" if is_new_file else "modify",
        "file": target_rel,
        "agent": getattr(args, "agent", "user:anonymous"),
        "reason": reason,
        "problem": problem,
        "approach": approach,
        "commit_hash": "",
        "force_write": bool(getattr(args, "force_write", False)),
        "files_changed": [target_rel],
        "old_content": old_content_diff,
        "new_content": new_content_diff,
        "lines_added": 0 if is_binary else _count_diff_lines(args, target, removed=False),
        "lines_removed": 0 if is_binary else _count_diff_lines(args, target, removed=True),
    }
    with audit_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    # === [8] git add + commit ===
    commit_hash = ""
    if config.get("git_enabled", True):
        try:
            # add 目标文件 + 审计日志（让 pre-commit hook 能放行）
            audit_rel = audit_path.relative_to(root)
            # Windows 路径分隔符统一为 /
            audit_rel_str = str(audit_rel).replace("\\", "/")
            target_rel_str = str(target_rel).replace("\\", "/")
            # Bug #21 fix: 用 _resolve_git_exe() 统一 git 可执行解析，
            # 与 doctor.py 检测逻辑保持一致（避免边缘场景 doctor OK / write 失败）
            GIT = _resolve_git_exe()
            # Bug #18 fix
            try:
                # v0.7.7 修复（BUG-05）：`audit_rel` 是 .pandaone/pandaone.jsonl，
                # 该文件被 .gitignore 排除（避免污染仓库）。普通 `git add` 会被 git 拒
                # 绝，导致审计日志跟 commit 失去原子绑定（commit 提交后审计 jsonl 还留在
                # 工作区，下次 write 又会被无脑信任旧基线）。用 `git add -f` 强制暂存，
                # 让审计日志跟本次 commit 一起进 git 历史、可回溯。
                r_add = subprocess.run(
                    [GIT, "add", "-f", target_rel_str, audit_rel_str],
                    cwd=str(root), capture_output=True, text=True, timeout=10,
                )
                if r_add.returncode != 0:
                    print(t("write_warn_git_add", err=r_add.stderr.strip()))
            except subprocess.TimeoutExpired:
                print(t("warn_subprocess_timeout", cmd="git add", timeout=10))
            commit_msg = (
                f"audit: {reason} [APPROVED]\n\n"
                f"file: {target_rel}\n"
                f"reason: {reason}\n"
                f"problem: {problem}\n"
                f"approach: {approach}\n"
            )
            r = subprocess.run(
                [GIT, "commit", "-m", commit_msg],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if r.returncode != 0:
                # hook 拒绝或 git 错误（不影响审计记录）
                pass
            if r.returncode == 0:
                # 获取 commit hash
                log_r = subprocess.run(
                    [GIT, "log", "-1", "--format=%H"],
                    cwd=str(root),
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                commit_hash = log_r.stdout.strip()
        except FileNotFoundError:
            print(t("write_warn_no_git"))

    print(f'[APPROVED] {{"status":"APPROVED","commit":"{commit_hash[:7]}","audit_id":"{audit_id}","file":"{target_rel}"}}')
    return 0
