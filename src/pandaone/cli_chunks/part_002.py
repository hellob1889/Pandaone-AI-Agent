# cli.py chunk 2/6: lines 325-728
# 子命令处理（逐步实现）
# PR #36 (v0.7.9): cli.py loader 现在 _exec_ns = globals() 直接共享,
# 之前 _exec_ns 复制 cli globals (包括所有 stdlib import).
# 现在 exec 时只能用 chunk 自己的 imports, 不能依赖 cli globals 已有 imports.
import sys
import os
import json
import hashlib
import subprocess
import time
from pathlib import Path
from datetime import datetime, timezone
# ============================================================
# 自指纹保护（L5 防御）
# ============================================================
# v0.7.23: 指纹与密码策略迁到独立模块 pandaone/fp_security.py。
#   原因: cli_chunks 单文件有 24KB 推送上限(MCP 单次推送限制),
#   而"可改密 + 常量时间比较 + 失败锁定 + 全包目录 manifest"
#   会持续膨胀。内聚到独立模块后, 本文件只留同名薄封装,
#   chunk 内部与外部(part_004/part_006/cmd_doctor)的调用点保持不变。
from pandaone.fp_security import (
    get_fingerprint_password as _fp_get_password,
    verify_password as _fp_verify_password,
    fp_lock_state as _fp_lock_state,
    register_failure as _fp_register_failure,
    clear_failures as _fp_clear_failures,
    reset_lock as _fp_reset_lock,
    set_fingerprint_password as _fp_set_password,
    clear_fingerprint_password as _fp_clear_password,
)

# 默认密码保留 "0000" —— 用户明确要求**必须有默认值**,
# 用户可自行改密(见 get_fingerprint_password 的优先级)。
_DEFAULT_FP_PASSWORD = "0000"


def get_fingerprint_password() -> str:
    """读取 CLI 自指纹更新密码。

    优先级（高 → 低）:
      1. 环境变量 PANDAONE_FP_PASSWORD（新名，推荐）
      2. 环境变量 PANDAX_FP_PASSWORD（旧名，已废弃，仅兼容存量脚本）
      3. 配置文件 ~/.pandaone/fp_password（用户自设，0600）
      4. 默认 "0000"（必须存在的默认值）

    详见 pandaone/fp_security.py。
    """
    return _fp_get_password()


def compute_fingerprint() -> str:
    """v0.7.23: 整个包目录（pandaone/ + pandaone_guard/）的聚合 SHA256。

    演进:
      v0.7.9 ~ v0.7.19  只哈希 cli.py 一个文件 → 改任意 chunk 都绕过
      v0.7.20 ~ v0.7.22 哈希 pandaone/ 下全部 *.py → 改资源文件仍绕过
      v0.7.23            哈希两个包目录下的**全部文件** → templates/、
                         installer/、index.html、banner.txt、*.ico 也在内

    排除 __pycache__/、*.pyc 等运行时产物（否则指纹每次运行都变）。
    实现见 pandaone/fp_security.py。
    """
    from pandaone import fp_security as _fpsec

    return _fpsec.compute_fingerprint()


def _get_pandaone_version() -> str:
    """v0.7.21.2: 取 pandaone 当前安装版本（指纹绑定用）。
    v0.7.22 fix: 源码树运行（开发模式）时必须取**源码里的 pyproject.toml 版本**,
    不能取 site-packages 的已安装版本 —— 否则改了源码但没重新安装时,
    版本号不变 → 指纹变化被判定成"篡改" → 所有子命令全挂。
    逻辑与 pandaone/__init__.py 的版本解析保持一致（源码 pyproject → metadata → 兜底）。
    """
    # 0. PyInstaller frozen (打包成 .exe)：既没有 pyproject.toml，也没有安装元数据。
    #    版本号由 build_pyinstaller.py 注入 _MEIPASS/pandaone/_build_info.py。
    try:
        import sys as _sys
        _mepass = getattr(_sys, "_MEIPASS", None)
        if _mepass:
            _bi = Path(_mepass) / "pandaone" / "_build_info.py"
            if _bi.is_file():
                import re as _re2
                _m2 = _re2.search(
                    r'__version__\s*=\s*"([^"]+)"',
                    _bi.read_text(encoding="utf-8"),
                )
                if _m2:
                    return _m2.group(1)
    except Exception:
        pass
    # 1. 源码树优先
    try:
        import importlib.util
        import re as _re
        _spec = importlib.util.find_spec("pandaone.cli_chunks.part_002")
        if _spec and _spec.origin:
            _repo_root = Path(_spec.origin).resolve().parents[3]  # .../<repo>/src/pandaone/cli_chunks/x.py
            _pyproject = _repo_root / "pyproject.toml"
            if _pyproject.is_file():
                _m = _re.search(
                    r'^\s*version\s*=\s*"([^"]+)"\s*$',
                    _pyproject.read_text(encoding="utf-8"),
                    _re.MULTILINE,
                )
                if _m:
                    return _m.group(1)
    except Exception:
        pass
    # 2. 已安装包元数据
    try:
        import importlib.metadata as _imd
        return _imd.version("pandaone-guard")
    except Exception:
        return "0.0.0+unknown"


def _now_iso() -> str:
    """ISO 8601 UTC 时间戳（委托 fp_security）。"""
    from pandaone import fp_security as _fpsec

    return _fpsec._now_iso()


def _save_fp(version: str, hash_hex: str) -> None:
    """v0.7.21.2: 存指纹到 FP_PATH (json 格式).

    v0.7.23: 实现下沉到 fp_security.save_fp；这里仍以 FP_PATH 为准，
    保证测试用 mock.patch.object(part_002, "FP_PATH") 依然生效。
    """
    from pandaone import fp_security as _fpsec

    _fpsec.save_fp(version, hash_hex, path=FP_PATH)


def _load_fp():
    """v0.7.21.2: 读 FP_PATH, 兼容旧裸 hex + 新 json 两种格式.

    Returns:
        (version, hash, migrated: bool)
        migrated=True 表示从旧裸 hex 迁移到新 json
    """
    from pandaone import fp_security as _fpsec

    return _fpsec.load_fp(path=FP_PATH)


def check_fingerprint(silent: bool = False, strict: bool = False) -> bool:
    """
    v0.7.21.2: 检查 pandaone.py 指纹, 支持版本号感知 + default auto-refresh.

    行为:
      - 首次运行: 生成 json 格式 {version, hash, stored_at}
      - hash match: 100% 通过 (True)
      - hash mismatch:
          - version 也变: 默认 auto-refresh (True) + info log
          - version 相同: 真篡改 → ERROR (False)
      - strict=True: 任何 hash mismatch 都报 ERROR (锁传统)
      - 旧裸 hex 格式: 自动迁移到 json, 触发一次 info log

    Returns:
        True = 通过 (auto-refresh 成功 / hash match / 首次生成)
        False = 失败 (strict 模式 hash mismatch / 同版本 hash 变)
    silent=True → 不打印任何错误（用于 --trust-default 模式）

    v0.7.34.0 — **stdout / stderr 契约**:
        本函数是 CLI 启动的**公共路径**（每次执行任何子命令都会经过）。
        机器端消费方（CI 脚本 / IDE 插件 / MCP）对 `pandaone doctor --json`
        的用法是 **json.loads(整个 stdout)** —— 所以 stdout 上**只能**有那一个
        JSON 文档。启动路径上的任何提示行都会让它直接抛
        "Expecting value: line 1 column 2"。

        因此：**所有 info 提示一律走 stderr**（诊断信息 ≠ 命令的正题），
        stdout 保持干净。终端里 stderr 照样显示，用户可见提示一点没少。
        ERROR 文案仍留在 stdout —— 那条路径下 CLI 直接 return 1、**根本不输出
        JSON**，机器端靠退出码分支，不靠解析 stdout（见 test_bug_48_trust_default.py）。
    """
    current = compute_fingerprint()
    current_version = _get_pandaone_version()

    if not FP_PATH.exists():
        # 首次运行：生成初始指纹 (json 格式)
        _save_fp(current_version, current)
        if not silent:
            # v0.7.34.0: 提示走 stderr（stdout 只留"命令的正题"）。
            #   这行只在"指纹不存在 / 需要刷新"时打印 —— 恰好就是用户刚升级完
            #   的第一个窗口，而那正是机器端第一次跑 doctor --json 的时刻。
            print(t("info_fp_generated", fp=current[:16]), file=sys.stderr)
        return True

    try:
        stored_version, stored_hash, migrated = _load_fp()
    except ValueError as e:
        if not silent:
            print(t("err_fingerprint_mismatch"))
            print(f"  {e}")
            print(f"  {t('err_fingerprint_hint')}")
        return False

    # 旧格式迁移 (裸 hex → json)
    if migrated:
        _save_fp(current_version, current)
        if not silent:
            # v0.7.34.0: 同上，提示一律走 stderr。
            print(t("info_fp_migrated"), file=sys.stderr)
            print(f"  {t('info_fp_generated', fp=current[:16])}", file=sys.stderr)
        return True

    # hash 匹配
    if stored_hash == current:
        return True

    # hash 不匹配
    if strict:
        if not silent:
            print(t("err_fp_strict_mismatch", old_hash=stored_hash[:16], new_hash=current[:16]))
            print(f"  {t('_stored', stored=stored_hash[:16])}")
            print(f"  {t('_current', current=current[:16])}")
            print(f"  {t('err_fingerprint_hint')}")
        return False

    # 默认模式: 版本号变了 → auto-refresh
    if stored_version != current_version:
        _save_fp(current_version, current)
        if not silent:
            # v0.7.34.0: 提示走 stderr。
            print(t("info_fp_auto_refreshed", old_version=stored_version, new_version=current_version, hash=current[:16]), file=sys.stderr)
        return True

    # 运行形态切换 → auto-refresh
    #   源码树 / pip 安装版  <->  PyInstaller 打包的 .exe 版
    # 两者文件集合不同（.exe 里没有 .py 源码，源码树里有 _build_info.py），
    # 指纹必然不同，但这是**合法部署行为**，不是篡改。
    #   没有这一分支的话：用户装完 .exe 第一次跑就会被 L5 判篡改 → CLI 全锁死。
    from pandaone import fp_security as _fpsec

    try:
        _rec = _fpsec.load_fp_record(path=FP_PATH)
        stored_form = _rec.get("form") or _fpsec.FORM_SOURCE
    except Exception:
        stored_form = _fpsec.FORM_SOURCE
    current_form = _fpsec.fp_form()
    if stored_form != current_form:
        _save_fp(current_version, current)
        if not silent:
            # v0.7.34.0: 提示走 stderr。
            print(t("info_fp_form_refreshed", old_form=stored_form, new_form=current_form, hash=current[:16]), file=sys.stderr)
        return True

    # 同版本号 + hash 变 = 真篡改
    # v0.7.22: 这里**不**给源码树模式开豁免。
    #   L5 的核心承诺是"agent 改了 pandaone 本体跳过审计，必须能检测到"，
    #   而 agent 完全可能在源码树上跑 —— 开发模式同样要检。
    #   源码改了之后的合法路径是**升版本号**：_get_pandaone_version() 现在
    #   会读源码树的 pyproject.toml，版本一变就自动刷新指纹（上面已处理）。
    if not silent:
        print(t("err_fingerprint_mismatch"))
        print(f"  {t('_stored', stored=stored_hash[:16])}")
        print(f"  {t('_current', current=current[:16])}")
        print(f"  {t('err_fingerprint_hint')}")
    return False


def cmd_init(args):
    """
    在指定目录初始化 Pandaone：
      - 创建 .pandaone/
      - 写 config.json
      - 写空的 pandaone.jsonl
    幂等：二次运行不报错。
    """
    import json

    root = Path(args.root).resolve()
    pandaone_dir = root / ".pandaone"

    # 创建目录（exist_ok=True 实现幂等）
    pandaone_dir.mkdir(parents=True, exist_ok=True)

    # 写 config.json
    # Phase 4.6: 默认保护 17 种常见文本格式（不只是 .py）
    # 覆盖：代码、配置、文档、前端、脚本五大类
    DEFAULT_PROTECTED_EXTENSIONS = [
        # 代码
        ".py", ".pyx",
        # 配置
        ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".env",
        # 文档
        ".md", ".rst", ".txt",
        # 前端
        ".html", ".css", ".js", ".ts",
        # 脚本
        ".sh", ".bat", ".ps1",
    ]
    # Bug #29 fix: --ext 支持逗号/空格分隔（argparse nargs='+' 已是 list）
    if args.ext:
        raw_exts = []
        for item in args.ext:
            # 每个 item 可能含逗号/空格分隔
            for e in str(item).replace(",", " ").split():
                if e.strip():
                    raw_exts.append(e.strip())
        protected_extensions = raw_exts
    else:
        protected_extensions = DEFAULT_PROTECTED_EXTENSIONS
    # 统一规范化：确保每个都以 "." 开头
    protected_extensions = [
        e if e.startswith(".") else f".{e}"
        for e in protected_extensions
    ]

    config = {
        "version": "1.0",
        "project_root": str(root),
        "protected_extensions": protected_extensions,
        # v0.7.34.0 M1: desktop.ini 是 Windows 的目录图标配置文件
        #   （Explorer / 系统自己管理，不是用户代码），不该纳入代码保护范围。
        #   之前它被 .ini 命中 → pandaone lock 之后 apply_desktop_icon()
        #   才写出可写的 desktop.ini → doctor 的 L1 永远 FAIL（用户跑了唯一
        #   的官方命令反而报红，且无解）。这里从默认排除项里去掉它。
        "exclude_patterns": ["__pycache__", "*.pyc", "_tmp_*.py", "_fix*.py", ".pandaone", ".git", "desktop.ini"],
        "git_enabled": True,
        "watchdog_enabled": True,
        "min_reason_length": 5,
        "min_problem_length": 10,
        "min_approach_length": 10,
    }
    # Phase 5: 二进制文件 SHA256 快照保护
    DEFAULT_BINARY_EXTENSIONS = [
        # 图片
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp",
        # 文档
        ".pdf", ".docx", ".xlsx", ".pptx",
        # 压缩
        ".zip", ".tar", ".gz", ".7z", ".rar",
        # 可执行
        ".exe", ".dll", ".so", ".dylib", ".bin",
        # 媒体
        ".mp4", ".mp3", ".wav", ".avi", ".mkv",
    ]
    config["binary_protected_extensions"] = [] if args.no_binary else DEFAULT_BINARY_EXTENSIONS
    exclude_patterns = config["exclude_patterns"]  # 提取出来给后续使用
    config_path = pandaone_dir / "config.json"

    # Bug #29 fix: 检测已存在 config 时保留用户自定义
    # 第一性原理：init 不是 idempotent overwrite，而是 merge-preserve
    # 已知字段：CLI 显式传入才覆盖（--ext, --no-binary）
    # 未知字段：用户自定义全部保留
    existing_config = None
    if config_path.exists():
        try:
            existing_config = json.loads(config_path.read_text(encoding="utf-8"))
            print(t("warn_init_config_exists", path=config_path))
        except (json.JSONDecodeError, OSError) as e:
            print(t("warn_init_config_corrupted", err=e))
            existing_config = None

    # Bug #29 fix: --force-reset 跳过 merge，用全新默认 config
    force_reset = getattr(args, "force_reset", False)

    if existing_config is not None and not force_reset:
        # Merge: 保留现有 + 只更新 CLI 显式指定的字段
        merged = dict(existing_config)
        # 项目路径和版本总是更新（init 在哪个目录就跑哪个目录）
        merged["version"] = "1.0"
        merged["project_root"] = str(root)
        # protected_extensions: 仅当 CLI 传 --ext 才覆盖
        if args.ext:
            raw = []
            for item in args.ext:
                for e in str(item).replace(",", " ").split():
                    if e.strip():
                        raw.append(e.strip())
            merged["protected_extensions"] = [
                e if e.startswith(".") else f".{e}" for e in raw
            ]
        # binary_protected_extensions: --no-binary 显式清空，否则保留现有
        if args.no_binary:
            merged["binary_protected_extensions"] = []
        # 其他字段（含 min_reason_length, custom fields）全部保留
        config = merged
    # else: 用刚构建的默认 config

    config_path.write_text(
        json.dumps(config, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # 写空审计日志
    audit_path = pandaone_dir / "pandaone.jsonl"
    if not audit_path.exists():
        audit_path.touch()

    # Phase 5: 创建二进制文件 SHA256 快照
    if config["binary_protected_extensions"]:
        _create_binary_snapshots(root, config["binary_protected_extensions"], exclude_patterns)

    print(t("ok_initialized", path=pandaone_dir))
    print(f"  {t('init_config', path=config_path)}")
    print(f"  {t('init_audit', path=audit_path)}")
    if config["binary_protected_extensions"]:
        print(f"  {t('init_binary', path=pandaone_dir / 'binary_snapshots.json')}")

    # 方案 A + Git 兼容性: 自动维护 .gitignore,避免 desktop.ini / .pandaone/ 被误 commit
    # 对抗式审查:
    #   - 只在 git 仓库里操作(非 git 目录不污染)
    #   - 幂等:已正确配置的不重复添加
    #   - 保留用户现有 .gitignore 条目
    try:
        from pandaone.gitignore_helper import ensure_gitignore
        changed, msg = ensure_gitignore(root)
        if "[SKIP]" not in msg:
            print(f"  {msg}")
    except ImportError:
        pass
    except Exception as e:
        print(f"  {t('warn_gitignore_failed', err=e)}")

    return 0


def _create_binary_snapshots(root: Path, binary_exts: list[str], exclude_patterns: list[str]):
    """
    Phase 5: 创建 binary_snapshots.json — 所有受保护二进制文件的 SHA256 字典。

    第一性原理：
      二进制无法做语义化 diff/审计，只能做完整性校验。
      snapshot 是审计的"基线"——所有变更必须以"approved write"形式留痕。

    对抗式审查：
      - 攻击：snapshot 文件本身被改 → 缓解：snapshot 在 .pandaone/ 里（被指纹 + exclude 保护）
      - 攻击：大文件 SHA256 慢 → 缓解：snapshot 仅在 init/approved write 时算一次
    """
    import hashlib
    import json
    import fnmatch as fnm

    snapshots = {}
    seen = set()
    for ext in binary_exts:
        for f in root.rglob(f"*{ext}"):
            if f in seen:
                continue
            seen.add(f)
            rel = f.relative_to(root)
            # 排除规则
            skip = False
            for pat in exclude_patterns:
                if any(fnm.fnmatch(part, pat) for part in rel.parts):
                    skip = True
                    break
                if fnm.fnmatch(rel.name, pat):
                    skip = True
                    break
            if skip:
                continue
            try:
                sha = hashlib.sha256(f.read_bytes()).hexdigest()
                snapshots[str(rel).replace("\\", "/")] = sha
            except OSError:
                pass

    snap_path = root / ".pandaone" / "binary_snapshots.json"
    snap_path.write_text(
        json.dumps(snapshots, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(t("info_snapshot_count", n=len(snapshots)))


def _update_binary_snapshot(root: Path, relpath: str, new_sha: str):
    """Phase 5: 更新单个文件的 SHA256 快照（approved write 后调用）"""
    import json
    snap_path = root / ".pandaone" / "binary_snapshots.json"
    if not snap_path.exists():
        return
    # Bug #16 fix: 捕获 JSONDecodeError
    try:
        snapshots = json.loads(snap_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(t("err_snapshot_corrupted", err=e))
        return
    # 统一为正斜杠
    relpath_normalized = relpath.replace("\\", "/")
    snapshots[relpath_normalized] = new_sha
    snap_path.write_text(
        json.dumps(snapshots, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def cmd_lock(args):
    """锁定所有 .py 文件（attrib +r / chmod ~0o222）

    Bug #28 (方案 A): 未初始化时自动调用 cmd_init（首次使用友好）
    高级用户可加 --no-auto-init 禁用自动 init
    """
    return _apply_readonly(args, readonly=True)


def cmd_unlock(args):
    """解锁所有 .py 文件（attrib -r / chmod +0o222）

    Bug #28: unlock 不自动 init（未 init 目录"解锁"无意义）
    """
    return _apply_readonly(args, readonly=False)


class _OldNotFoundError(Exception):
    """Bug #12: 业务拒绝异常 --old 字符串不在文件中。
    让 write 流程用统一的 try/finally 处理，无需散落的 inline 拒绝代码。"""
    def __init__(self, snippet: str):
        super().__init__(snippet)
        self.snippet = snippet


def _info_length(s: str) -> int:
    """
    Bug #9/#10 fix: 计算字符串的"信息长度"（unicode 显示宽度）。

    第一性原则：阈值应当反映"内容是否有足够语义价值"，而不是字符数。
    - 1 个 CJK 字符（中文/日文/韩文）= 2 宽度单位（信息密度 ≈ 2 个英文字符）
    - 1 个 Fullwidth 字符（全角标点）= 2 宽度单位
    - 1 个 ASCII/拉丁字符 = 1 宽度单位
    - 控制字符 = 0

    修复前：len("测试") == 2，被 reason 阈值 (5 chars) 误伤
    修复后：info_len("测试") == 4，仍然 < 5 阈值 — 仍可能被误伤
           所以同时降低阈值到合理水平（reason 5、problem/approach 10）

    典型用例：
    - "fix" (3 chars) → 3，< 5 拒绝（合理）
    - "测试" (2 chars) → 4，< 5 拒绝（仍然）
    - "测试写" (3 chars) → 6，≥ 5 通过（中文短句 OK）
    - "fix bug" (7 chars) → 7，≥ 5 通过
    - "需要修复初始化函数" (9 chars) → 18，≥ 5 通过
    """
    import unicodedata as _ud
    n = 0
    for ch in s:
        if not ch.isprintable():
            continue  # 跳过控制字符（不计入信息量）
        width = _ud.east_asian_width(ch)
        if width in ("W", "F"):  # Wide / Fullwidth
            n += 2
        else:  # Na / H / A / N
            n += 1
    return n


def _count_diff_lines(args, target: Path, removed: bool = False) -> int:
    """v0.7.3: 计算 diff 行数"""
    try:
        if args.old and args.new:
            if removed:
                return max(1, args.old.count("\n") + 1)
            else:
                return max(1, args.new.count("\n") + 1)
        elif args.content:
            new_lines = max(1, args.content.count("\n") + 1)
            if removed:
                try:
                    old_text = target.read_text(encoding="utf-8")
                    return max(1, old_text.count("\n") + 1)
                except Exception:
                    return 0
            return new_lines
    except Exception:
        return 0
    return 0


def _colorize(text: str, color: str) -> str:
    """v0.7.3: ANSI 颜色"""
    if os.environ.get("NO_COLOR"):
        return text
    codes = {
        "red": "\033[31m", "green": "\033[32m", "yellow": "\033[33m",
        "blue": "\033[34m", "magenta": "\033[35m", "cyan": "\033[36m",
        "white": "\033[37m", "gray": "\033[90m", "bold": "\033[1m",
        "reset": "\033[0m",
    }
    return f"{codes.get(color, '')}{text}{codes['reset']}"


def _effective_suffix(path: Path) -> str:
    """
    Phase 4.6+: 返回文件的有效后缀（正确处理隐藏文件如 .env, .gitignore, .env.local）。

    标准 Path.suffix 行为：
      - main.py → .py
      - .env → '' （隐藏文件被当作无后缀）
      - .gitignore → ''
      - .env.local → .local

    我们希望的"有效后缀"语义：
      - main.py → .py
      - .env → .env （整名就是后缀）
      - .gitignore → .gitignore
      - .env.local → .local （保留最后一段，符合 POSIX 习惯）

    第一性原理：
      隐藏文件经常包含敏感配置（.env = 数据库密码），必须被审计保护。
      标准 pathlib 把它们当无后缀处理 = 安全漏洞。
    """
    name = path.name
    if name.startswith("."):
        rest = name[1:]  # 去掉前导点
        if "." in rest:
            # .env.local → .local
            return "." + rest.rsplit(".", 1)[1]
        # .env → .env
        return "." + rest
    return path.suffix