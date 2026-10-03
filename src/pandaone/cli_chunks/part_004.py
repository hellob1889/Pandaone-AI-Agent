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
        # v0.7.15 fix: 之前静默 return 1，用户不知道发生了什么。
        print(t("log_not_initialized", path=str(Path(args.root).resolve() / ".pandaone" / "pandaone.jsonl")))
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
        # v0.7.15 fix: 同 cmd_log，静默失败改为明确提示。
        print(t("log_not_initialized", path=str(Path(args.root).resolve() / ".pandaone" / "pandaone.jsonl")))
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
        print("--- record ---")
        # v0.7.15 fix: header_line 之前拼好但从未输出（死代码），
        # 导致 log 看不到审计记录 ID / 时间 / agent，也无法与 CI 报告交叉引用。
        print(header_line)
        # v0.7.15 fix (Bug #14): 字段标签本地化（zh: 文件:/原因:... en: File:/Reason:...）
        print(f"{t('log_label_file')}: {file_}")
        commit = rec.get("commit_hash") or "no_commit"
        print(f"{t('log_label_commit')}: {commit[:12]}")
        if status == "APPROVED":
            print(f"{t('log_label_reason')}: {rec.get('reason', '')}")
            print(f"{t('log_label_problem')}: {rec.get('problem', '')}")
            print(f"{t('log_label_approach')}: {rec.get('approach', '')}")
        elif status == "REJECTED":
            print(f"{t('log_label_rejection')}: {rec.get('rejection_reason', '')}")
        # v0.7.15: 补上 v0.7.3 承诺的面板特性 — 行数统计 + diff 内容段。
        #   之前面板只显示文件/提交/原因，看不到改了什么（RED 测试悬空至今）。
        _added = rec.get("lines_added", 0) or 0
        _removed = rec.get("lines_removed", 0) or 0
        if _added or _removed:
            print(f"{t('log_label_lines')}: +{_added} -{_removed}")
        _old_c = rec.get("old_content", "") or ""
        _new_c = rec.get("new_content", "") or ""
        if _old_c or _new_c:
            _max_lines = None if verbose else 4
            print(t("log_label_diff"))
            if _old_c:
                _old_lines = _old_c.rstrip("\n").splitlines()
                for _ln in _old_lines[:_max_lines]:
                    print(f"  - {_ln}")
                if _max_lines and len(_old_lines) > _max_lines:
                    print(f"  - ... (+{len(_old_lines) - _max_lines})")
            if _new_c:
                _new_lines = _new_c.rstrip("\n").splitlines()
                for _ln in _new_lines[:_max_lines]:
                    print(f"  + {_ln}")
                if _max_lines and len(_new_lines) > _max_lines:
                    print(f"  + ... (+{len(_new_lines) - _max_lines})")
        print("--- end ---")


def _pid_alive(pid_text: str) -> bool:
    """v0.7.15: 探测 watchdog PID 是否存活（POSIX 用 signal 0 探测）"""
    try:
        pid = int(pid_text.strip())
    except (ValueError, AttributeError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True  # 进程存在但属主不同
    except OSError:
        return False


def cmd_status(args):
    """显示项目状态仪表盘。"""
    import json
    import stat
    root = Path(args.root).resolve()
    pandaone_dir = root / ".pandaone"
    if not pandaone_dir.exists():
        # v0.7.15 fix: 之前静默 return 1，用户不知道为什么没输出。
        print(t("status_not_initialized", root=str(root)))
        return 1
    print("=" * 64)
    print(t("status_header", root=root))
    print("=" * 64)
    protected_files = _iter_protected_files(root, {})
    if protected_files:
        locked = sum(1 for p in protected_files if not (p.stat().st_mode & stat.S_IWUSR))
        unlocked = len(protected_files) - locked
        print(t("status_l1"))
        print(t("status_total", n=len(protected_files)))
        print(t("status_locked_unlocked", n=locked, m=unlocked))
    # v0.7.15 fix: L2 watchdog 区块。i18n key (status_l2/status_watch_on/
    # status_watch_off) 早已存在，但实现一直没接上（RED 测试悬空）。
    print()
    print(t("status_l2"))
    pid_path = pandaone_dir / ".watchdog_pid"
    if pid_path.exists():
        pid_text = pid_path.read_text(encoding="utf-8").strip()
        if _pid_alive(pid_text):
            print(t("status_watch_on", pid=pid_text))
        else:
            print(t("status_watch_off"))
    else:
        print(t("status_watch_off"))
    print()
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
        print(t("status_total_records", n=total))
        # v0.7.15 fix (Bug #17): 状态计数用本地化标签，不再裸输出 APPROVED 等
        n_approved = sum(1 for r in records if r.get("status") == "APPROVED")
        n_rejected = sum(1 for r in records if r.get("status") == "REJECTED")
        n_unauth = sum(1 for r in records if r.get("status") == "UNAUTHORIZED")
        if n_approved:
            print(t("status_count_approved", n=n_approved))
        if n_rejected:
            print(t("status_count_rejected", n=n_rejected))
        if n_unauth:
            print(t("status_count_unauthorized", n=n_unauth))
    print()
    print("=" * 64)
    return 0
