# -*- coding: utf-8 -*-
"""
audit_binding.py — 审计内容绑定（content binding）核心判定
===========================================================

为什么需要这个模块（第一性原理）
--------------------------------
审计承诺是"**这一次改动**被审过"，不是"**这个路径**被审过"。

只按路径放行 = 一次旧审批可以无限期放行该文件之后的任意改写。
实测复现（A1 盲区）：app.py 一年前审计过一次 → 今天把它完全改写成
`import os; os.system('echo PWNED')`，不做任何新审计 →
  - pre-commit hook      → exit 0（放行）
  - pandaone ci          → exit 0（"[OK] PASS — 所有变更均已审计"）

本模块把审批与**内容 SHA256** 绑定：
  - 写审计记录时（cmd_write）落 content_sha256
  - 校验时（hook / ci）取**待提交内容**的 SHA256 与之比对
  - 不一致 = 内容被改写且没有重新审计 = 拒绝

设计约束
--------
1. **纯逻辑**：不 import i18n、不 print、不依赖主包其它模块。
   hook 模板（安装到 .pandaone/ 的独立副本）与 cmd_ci（主包）
   共用同一份判定，避免两处实现漂移。
2. **只调 git CLI**：hook 环境里 git 可能不在 PATH，
   git 可执行路径由调用方解析后传进来（本模块不猜路径）。
3. **渐进增强（兼容性）**：存量审计记录没有 content_sha256 字段
   （本项目历史 277+ 条全都没有）。若"必须有哈希才放行"，
   升级后所有存量项目的 hook 会突然拒绝所有提交。
   因此：
     - 该文件有带 content_sha256 的 APPROVED 记录 → 严格比对哈希
     - 该文件只有无哈希的旧记录 → 保留原有"路径成员"判定放行 + warn
     - 该文件完全没有 APPROVED 记录 → 拒绝
"""
import hashlib
import json
import subprocess

# ============================================================
# 判定状态
# ============================================================

#: 内容哈希与审批记录一致 → 放行
STATUS_OK = "ok"
#: 该文件只有无 content_sha256 的旧记录 → 按路径放行（+ warn）
STATUS_LEGACY = "legacy"
#: 内容哈希不一致 → 拒绝（内容被改写且未重新审计）
STATUS_MISMATCH = "mismatch"
#: 该文件没有任何 APPROVED 记录 → 拒绝
STATUS_NO_RECORD = "no_record"
#: 取不到待校验内容 → 拒绝（fail closed）
STATUS_NO_CONTENT = "no_content"


# ============================================================
# 哈希工具
# ============================================================

def sha256_bytes(data: bytes) -> str:
    """字节流的 SHA256（十六进制小写）。"""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path) -> str:
    """文件**原始字节**的 SHA256；读不到返回 ""。

    注意：这是工作区文件的字节，不是 git index 里的字节。
    两者在有 .gitattributes / core.autocrlf 时**可能不同**
    （Windows 上 write_text 写 CRLF，index 里存 LF），
    所以审计绑定必须用 index blob 的哈希，见 index_blob_map()。
    """
    try:
        with open(str(path), "rb") as f:
            return sha256_bytes(f.read())
    except OSError:
        return ""


def norm_rel(path) -> str:
    """统一成 POSIX 风格（反斜杠 → 正斜杠），用于路径比较。"""
    return str(path or "").replace("\\", "/").strip()


def effective_suffix(rel_path: str) -> str:
    """dotfile 感知的"有效后缀"。

    标准 pathlib 语义（``Path(".env").suffix == ''``）会让 .env 这种
    隐藏文件永远逃过扩展名检查 —— 而 .env 恰恰是最该被审计的。
    与 cli_chunks/part_002.py 的 ``_effective_suffix`` 保持同一语义：

      main.py      → .py
      .env         → .env      （隐藏文件：整名就是后缀）
      .env.local   → .local    （保留最后一段）
      .gitignore   → .gitignore
      noext        → ''        （无点）
    """
    name = norm_rel(rel_path).rsplit("/", 1)[-1]
    if not name:
        return ""
    if name.startswith("."):
        rest = name[1:]
        if "." in rest:
            return "." + rest.rsplit(".", 1)[1]
        return "." + rest
    idx = name.rfind(".")
    if idx <= 0:
        return ""
    return name[idx:]


# ============================================================
# git CLI 封装（只取字节，不做路径/编码猜测）
# ============================================================

def _run_git(git_exe, repo_root, args, timeout=15):
    """跑一条 git 命令，返回 CompletedProcess（stdout 为 bytes）；失败返回 None。"""
    if not git_exe:
        return None
    try:
        return subprocess.run(
            [str(git_exe)] + [str(a) for a in args],
            cwd=str(repo_root),
            capture_output=True,
            timeout=timeout,
        )
    except Exception:
        return None


def staged_paths(git_exe, repo_root, diff_filter="ACMR"):
    """列出 staged（index）里变更的文件路径。

    - ``--diff-filter=ACMR``：Added / Copied / Modified / Renamed
      旧实现只用 "AM"，漏掉 R（rename）与 C（copy）：
      ``git mv a.py b.py`` 之后 b.py 根本不在检查集里 → 改名即逃逸。
    - rename/copy 只取**新路径**（旧路径已从 index 消失）：
      新路径必须独立审批。

    返回 None 表示 git 调用失败（调用方应 fail closed）。
    """
    r = _run_git(git_exe, repo_root,
                 ["diff", "--cached", "--name-status", "-z",
                  "--diff-filter=" + diff_filter])
    if r is None or r.returncode != 0:
        return None
    fields = r.stdout.decode("utf-8", errors="replace").split("\0")
    paths = []
    i = 0
    while i < len(fields):
        status = fields[i]
        i += 1
        if not status:
            continue
        code = status[0]
        if code in ("R", "C"):
            # R/C 后面跟两个路径：old、new（只取 new）
            if i + 1 < len(fields):
                paths.append(norm_rel(fields[i + 1]))
            i += 2
        else:
            if i < len(fields):
                paths.append(norm_rel(fields[i]))
            i += 1
    return paths


def index_blob_map(git_exe, repo_root):
    """index（= staged 内容）里所有路径 → blob sha。

    为什么必须用 index 而不是工作区文件：
    工作区可能又改了但还没 add。真正要提交的是 index 里的内容。
    """
    r = _run_git(git_exe, repo_root, ["ls-files", "--stage", "-z"])
    out = {}
    if r is None or r.returncode != 0:
        return out
    for entry in r.stdout.decode("utf-8", errors="replace").split("\0"):
        if not entry:
            continue
        meta, _, path = entry.partition("\t")
        # `git ls-files --stage` 的字段顺序是: <mode> <object> <stage>\t<path>
        # （object 才是 blob sha —— 取错字段会拿到 "100644" 这种 mode）
        parts = meta.split()
        if len(parts) >= 3 and path:
            out[norm_rel(path)] = parts[1]
    return out


def ref_blob_map(git_exe, repo_root, ref):
    """某个 ref（commit）里所有路径 → blob sha（CI 用）。"""
    r = _run_git(git_exe, repo_root, ["ls-tree", "-r", "-z", str(ref)])
    out = {}
    if r is None or r.returncode != 0:
        return out
    for entry in r.stdout.decode("utf-8", errors="replace").split("\0"):
        if not entry:
            continue
        meta, _, path = entry.partition("\t")
        # `git ls-tree` 的字段顺序是: <mode> <type> <object>\t<path>
        parts = meta.split()
        if len(parts) >= 3 and path:
            out[norm_rel(path)] = parts[2]
    return out


def blob_bytes(git_exe, repo_root, blob_sha):
    """取某个 blob 的原始字节；取不到返回 None。"""
    if not blob_sha:
        return None
    r = _run_git(git_exe, repo_root, ["cat-file", "blob", str(blob_sha)])
    if r is None or r.returncode != 0:
        return None
    return r.stdout


def index_blob_bytes(git_exe, repo_root, rel_path):
    """取 index 里某个路径的字节（staged 的真实内容）。"""
    sha = index_blob_map(git_exe, repo_root).get(norm_rel(rel_path))
    return blob_bytes(git_exe, repo_root, sha)


# ============================================================
# 审计记录
# ============================================================

def load_audit_records(audit_path):
    """读审计日志（.pandaone/pandaone.jsonl），返回记录 dict 列表。"""
    records = []
    try:
        with open(str(audit_path), "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if isinstance(rec, dict):
                    records.append(rec)
    except OSError:
        return []
    return records


def approved_records_for(records, rel_path):
    """某个文件的全部 APPROVED 记录（按日志先后顺序）。"""
    target = norm_rel(rel_path)
    out = []
    for rec in records or []:
        if str(rec.get("status", "")).upper() != "APPROVED":
            continue
        if norm_rel(rec.get("file")) == target:
            out.append(rec)
    return out


def binding_hash_for(records, rel_path):
    """该文件**最近一条带 content_sha256 的 APPROVED 记录**的哈希。

    没有带哈希的记录 → 返回 ""（= legacy 记录，只能按路径放行）。
    """
    h = ""
    for rec in approved_records_for(records, rel_path):
        val = rec.get("content_sha256")
        if isinstance(val, str) and val.strip():
            h = val.strip().lower()
    return h


def verify_content(rel_path, content_bytes, records):
    """核心判定：给定「路径 + 待提交内容字节 + 审计记录」→ 判定结果。

    返回 dict：
      {"status": one of STATUS_*,
       "expected": 记录里绑定的 SHA256（"" 表示 legacy）,
       "actual":   实际算出的 SHA256,
       "record_id": 用到的审计记录 id}
    """
    recs = approved_records_for(records, rel_path)
    if not recs:
        return {"status": STATUS_NO_RECORD, "expected": "", "actual": "",
                "record_id": ""}
    expected = binding_hash_for(records, rel_path)
    record_id = str(recs[-1].get("id", ""))
    if not expected:
        # 存量记录：没绑定内容 → 按路径放行（调用方负责打 warn）
        return {"status": STATUS_LEGACY, "expected": "", "actual": "",
                "record_id": record_id}
    if content_bytes is None:
        return {"status": STATUS_NO_CONTENT, "expected": expected, "actual": "",
                "record_id": record_id}
    actual = sha256_bytes(content_bytes)
    status = STATUS_OK if actual == expected else STATUS_MISMATCH
    return {"status": status, "expected": expected, "actual": actual,
            "record_id": record_id}
