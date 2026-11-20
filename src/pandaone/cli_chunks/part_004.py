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
            # v0.7.18 fix: 渲染 attempted_* ——「被拒绝的那次到底想写什么」。
            #
            # 背景：审计记录在写入被拒时**已经**保存了 attempted_reason /
            # attempted_problem / attempted_approach（见 part_003 的 REJECTED 分支），
            # 翻译 key `log_attempted` 也早就在 i18n 双语包里定义好了 ——
            # 但 `_print_log` 从来没有调用过它，这条翻译是一条**死翻译**。
            #
            # 后果（对审计产品是实质缺陷）：被拒绝的写入只留一句"为什么拒绝"，
            # 不留"当时想写什么"。审计留痕最关键的那一半丢了 ——
            # 事后复盘时你能看到"这次被拦了"，却看不到"被拦的是什么"。
            #
            # 暴露方式：tests/test_e2e.py::test_full_workflow_e2e 断言
            # `log --rejected` 输出含 "attempted"/"尝试"。该测试长期在 CI 上
            # （非 root runner）真实执行并失败，但 publish.yml 的 test job
            # 不接 `needs`，失败既不阻塞发布也无人查看；
            # 本地跑则因 euid==0 被 `_ROOT_SKIP` 静默跳过 —— 两头都看不见。
            if any(rec.get(k) for k in ("attempted_reason", "attempted_problem", "attempted_approach")):
                print(t(
                    "log_attempted",
                    reason=rec.get("attempted_reason") or "-",
                    problem=rec.get("attempted_problem") or "-",
                    approach=rec.get("attempted_approach") or "-",
                ))
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
    """探测 watchdog PID 是否存活（跨平台用 psutil.pid_exists）。

    v0.7.35: 实现已下沉到 pandaone.health_probe.pid_alive —— status 与 doctor
    必须用同一套进程存活判定，否则"PID 还在"会在两个命令上给出不同结论。
    """
    from pandaone.health_probe import pid_alive
    return pid_alive(pid_text)


def cmd_status(args):
    """显示项目状态仪表盘。

    v0.7.35: L1 / L2 / L5 / L6 的判据全部下沉到 ``pandaone.health_probe`` ——
    **与 doctor 共用同一份**。历史上这两个命令各写各的判据，已经漂移过三次：

      1. L1 传空 config → ``config.get("protected_extensions", [".py"])``
         永远拿到默认的 ``[".py"]`` → 631 个受保护文件在仪表盘上完全不可见。
      2. L2 只查 PID 存活 → 看门狗被强杀后 PID 残留，而 PID 会被系统回收
         复用 → 别的进程拿到同一个 PID → 假绿。
      3. L5 直接比 hash、丢掉 form → pip 版与 exe 版共存（合法部署行为）时
         误报"不匹配"。

    三态语义（与 doctor 一致）：na（未启用）/ ok / fail；
    **fail 会让退出码变成 3**（与 doctor 的层级失败退出码一致），便于脚本判断。
    """
    from pandaone import health_probe as _hp

    root = Path(args.root).resolve()
    pandaone_dir = root / ".pandaone"
    if not pandaone_dir.exists():
        # v0.7.15 fix: 之前静默 return 1，用户不知道为什么没输出。
        print(t("status_not_initialized", root=str(root)))
        return 1
    print("=" * 64)
    print(t("status_header", root=root))
    print("=" * 64)

    #: FAIL 态的层（决定退出码）；na 态（未启用）不算失败。
    failed = []

    def _show(st):
        """按三态打印一行状态。"""
        state = st.get("state")
        if state == _hp.OK:
            print(t("status_state_ok", note=st.get("note", "")))
        elif state == _hp.NA:
            print(t("status_state_na", note=st.get("note", "")))
        elif state == _hp.WARN:
            print(t("status_state_warn", note=st.get("note", "")))
        else:
            print(t("status_state_fail", note=st.get("note", "")))

    # ---------------- L1 文件锁 ----------------
    print(t("status_l1"))
    l1 = _hp.file_lock_state(root)
    _show(l1)
    if l1["state"] == _hp.FAIL:
        failed.append("L1")
    if l1.get("total"):
        print(t("status_total", n=l1["total"]))
        print(t("status_locked_unlocked", n=l1.get("locked", 0), m=l1.get("writable", 0)))

    # ---------------- L2 watchdog ----------------
    print()
    print(t("status_l2"))
    l2 = _hp.watchdog_state(root)
    if l2["state"] == _hp.OK:
        print(t("status_watch_on", pid=l2.get("pid", "")))
    elif l2["state"] == _hp.NA:
        print(t("status_watch_off"))
    else:
        # 跑过但坏了：进程不在，或 PID 被别的进程复用（假绿）
        print(t("status_state_fail", note=l2.get("note", "")))
        failed.append("L2")

    # ---------------- L5 自指纹 ----------------
    print()
    print(t("status_l5"))
    l5 = _hp.fingerprint_state()
    if l5["state"] == _hp.OK:
        print(t("status_fp_ok", fp=str(l5.get("current", ""))[:16]))
    elif l5["state"] == _hp.WARN:
        # 形态切换 / 版本升级 = 合法部署行为，不是篡改
        print(t("status_fp_switch", note=l5.get("note", "")))
    elif l5["state"] == _hp.NA:
        print(t("status_fp_uninit"))
    else:
        print(t("status_fp_tampered", note=l5.get("note", "")))
        failed.append("L5")

    # ---------------- 审计统计 ----------------
    print()
    print(t("status_audit_stats"))
    audit = _hp.audit_state(root)
    audit_path = pandaone_dir / "pandaone.jsonl"
    if audit_path.exists():
        print(t("status_total_records", n=audit.get("total", 0)))
        # v0.7.15 fix (Bug #17): 状态计数用本地化标签，不再裸输出 APPROVED 等
        if audit.get("approved"):
            print(t("status_count_approved", n=audit["approved"]))
        if audit.get("rejected"):
            print(t("status_count_rejected", n=audit["rejected"]))
        if audit.get("unauthorized"):
            print(t("status_count_unauthorized", n=audit["unauthorized"]))
    if audit["state"] == _hp.FAIL:
        print(t("status_state_fail", note=audit.get("note", "")))
        failed.append("L6")

    print()
    print("=" * 64)
    if failed:
        print(t("status_failed_layers", layers=", ".join(failed)))
        return 3
    return 0
