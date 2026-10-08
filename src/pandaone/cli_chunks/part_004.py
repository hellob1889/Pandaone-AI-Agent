# cli.py chunk 4/6: lines 1202-1611
def _query_records(args):
    """共享 query + filter 逻辑（cmd_log 和 cmd_export 共用）。"""
    import json
    root = Path(args.root).resolve()
    audit_path = root / ".pandaone" / "pandaone.jsonl"
    if not audit_path.exists():
        return [], None
    records = []
    for line in audit_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    filtered = records
    if getattr(args, "file", ""):
        filtered = [r for r in filtered if r.get("file") == args.file]
    if getattr(args, "session", ""):
        filtered = [r for r in filtered if r.get("session_id") == args.session]
    if getattr(args, "rejected", False):
        filtered = [r for r in filtered if r.get("status") == "REJECTED"]
    if getattr(args, "unauthorized", False):
        filtered = [r for r in filtered if r.get("status") == "UNAUTHORIZED"]
    if getattr(args, "recent", 0) and getattr(args, "recent", 0) > 0:
        filtered = filtered[-args.recent:]
    if getattr(args, "agent", ""):
        target_agent = args.agent
        filtered = [r for r in filtered if r.get("agent") == target_agent]
    return filtered, root


def cmd_log(args):
    """查询审计历史。"""
    filtered, root = _query_records(args)
    if root is None:
        return 1
    if getattr(args, "export", ""):
        from .exporters import export_html
        out_path = Path(args.export)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        export_html(filtered, out_path)
        print(t("log_export_ok", n=len(filtered), path=out_path))
        return 0
    if getattr(args, "format", "") or getattr(args, "output", ""):
        if not getattr(args, "format", ""):
            print(t("err_format_without_format"))
            return 1
        if not getattr(args, "output", ""):
            print(t("err_format_without_output"))
            return 1
        print(t("warn_log_export_use_export_subcommand"))
    if getattr(args, "format", "") and getattr(args, "output", ""):
        from .exporters import export_records
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        ok = export_records(filtered, args.format, out_path)
        if not ok:
            return 1
        print(t("log_export_ok_format", n=len(filtered), fmt=args.format, path=out_path))
        return 0
    _print_log._verbose = getattr(args, "verbose", False)
    _print_log(filtered)
    _print_log._verbose = False
    return 0


def cmd_export(args):
    """Bug #25 fix: 独立 export 子命令。"""
    filtered, root = _query_records(args)
    if root is None:
        return 1
    if not getattr(args, "format", ""):
        print(t("export_err_no_format"))
        return 1
    if not getattr(args, "output", ""):
        print(t("export_err_no_output"))
        return 1
    from .exporters import export_records
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ok = export_records(filtered, args.format, out_path)
    if not ok:
        return 1
    print(t("export_ok", n=len(filtered), fmt=args.format, path=out_path))
    return 0


def _render_unified_diff(old: str, new: str, file_path: str):
    """Bug fix (v0.7.15) F-04 A2: --verbose 时显示 unified diff。

    Args:
        old: 修改前内容（可能为空表示新增）
        new: 修改后内容（可能为空表示删除）
        file_path: 文件路径（仅用于 diff header label）
    """
    import difflib
    old_lines = old.splitlines(keepends=True) if old else []
    new_lines = new.splitlines(keepends=True) if new else []
    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"{file_path} (before)",
        tofile=f"{file_path} (after)",
        lineterm="",
    )
    added = 0
    removed = 0
    for line in diff:
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
        print(line)
    print(f"  [diff] Lines: +{added} -{removed}")


def _print_log(records):
    """格式化输出审计记录（v0.7.3 面板格式）"""
    verbose = getattr(_print_log, "_verbose", False)
    if not records:
        print(t("log_no_records"))
        return
    print("=" * 80)
    print(t("log_header", n=len(records)))
    print("=" * 80)
    for rec in records:
        ts = rec.get("timestamp", "?")
        status = rec.get("status", "?")
        rid = rec.get("id", "?")
        file_ = rec.get("file", "?")
        agent = rec.get("agent", "user:anonymous")
        if status == "APPROVED":
            status_icon = _colorize("OK APPROVED", "green")
        elif status == "REJECTED":
            status_icon = _colorize("X REJECTED", "red")
        elif status == "UNAUTHORIZED":
            status_icon = _colorize("WARN UNAUTHORIZED", "yellow")
        else:
            status_icon = status
        header_line = f"{status_icon} - {rid} - {ts} - by {_colorize(agent, 'cyan')}"
        print(header_line)  # Bug fix (v0.7.15): 之前构造了 header_line 但从未打印
        print("--- record ---")
        # Bug fix (v0.7.15) F-02 A1: 走 t() 本地化，避免裸英文 label
        print(f"{t('log_field_file')}: {file_}")
        commit = rec.get("commit_hash") or "no_commit"
        print(f"{t('log_field_commit')}: {commit[:12]}")
        if status == "APPROVED":
            print(f"{t('log_field_reason')}: {rec.get('reason', '')}")
            print(f"{t('log_field_problem')}: {rec.get('problem', '')}")
            print(f"{t('log_field_approach')}: {rec.get('approach', '')}")
            # Bug fix (v0.7.15) F-04 A2: verbose 时显示 old/new unified diff
            verbose = bool(getattr(_print_log, "_verbose", False))
            old_content = rec.get("old_content", "")
            new_content = rec.get("new_content", "")
            if verbose and (old_content or new_content):
                _render_unified_diff(old_content, new_content, file_)
        elif status == "REJECTED":
            print(f"{t('log_field_rejection')}: {rec.get('rejection_reason', '')}")
        print("--- end ---")


def cmd_status(args):
    """显示项目状态仪表盘。"""
    import json
    import stat
    root = Path(args.root).resolve()
    pandaone_dir = root / ".pandaone"
    if not pandaone_dir.exists():
        # 未初始化：打印中英双语错误信息（与 test_status_handles_no_init 对齐）
        # Bug fix (v0.7.15): 之前 silent return 1，用户看不到任何错误
        # 复用已有 i18n key（与 cmd_write 等保持一致）
        print(t("err_write_root_not_init", root=root))
        return 1
    print("=" * 64)
    print(t("status_header", root=root))
    print("=" * 64)
    # [L1] 文件锁状态
    protected_files = _iter_protected_files(root, {})
    if protected_files:
        locked = sum(1 for p in protected_files if not (p.stat().st_mode & stat.S_IWUSR))
        unlocked = len(protected_files) - locked
        print(t("status_l1"))
        print(t("status_total", n=len(protected_files)))
        print(t("status_locked_unlocked", n=locked, m=unlocked))
    print()
    # [L2] Watchdog 状态 — 第一性原理：用户需要知道后台监控是否在跑
    # 之前缺失此段，test_status_shows_watchdog_pid / test_status_watchdog_not_running 失败
    # 复用已有 i18n key：status_watch_on / status_watch_off（保持 i18n 风格统一）
    pid_file = pandaone_dir / ".watchdog_pid"
    print(t("status_l2"))
    if pid_file.exists():
        try:
            pid_str = pid_file.read_text(encoding="utf-8").strip()
            print(t("status_watch_on", pid=pid_str))
        except Exception:
            print(t("status_watch_off"))
    else:
        print(t("status_watch_off"))
    print()
    # [L5] 指纹状态
    print(t("status_l5"))
    if FP_PATH.exists():
        stored = FP_PATH.read_text(encoding="utf-8").strip()
        current = compute_fingerprint()
        if stored == current:
            print(t("status_fp_ok", fp=stored[:16]))
        else:
            print(t("status_fp_mismatch", stored=stored[:16], current=current[:16]))
    else:
        print(t("status_fp_uninit"))
    print()
    # 审计统计
    audit_path = pandaone_dir / "pandaone.jsonl"
    print(t("status_audit_stats"))
    if audit_path.exists():
        records = []
        for line in audit_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        total = len(records)
        approved = sum(1 for r in records if r.get("status") == "APPROVED")
        rejected = sum(1 for r in records if r.get("status") == "REJECTED")
        unauthorized = sum(1 for r in records if r.get("status") == "UNAUTHORIZED")
        print(t("status_total_records", n=total))
        print(t("status_count_approved", n=approved))
        print(t("status_count_rejected", n=rejected))
        print(t("status_count_unauthorized", n=unauthorized))
        # Bug fix (v0.7.15) F-05: UNAUTHORIZED 段显示非授权写入警告
        if unauthorized > 0:
            recent_unauth = [r for r in records if r.get("status") == "UNAUTHORIZED"][-3:]
            recent_files = ", ".join(r.get("file", "?") for r in recent_unauth)
            print(t("status_unauthorized_warn", n=unauthorized, recent_files=recent_files))
    print()
    print("=" * 64)
    return 0
