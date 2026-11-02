# -*- coding: utf-8 -*-
"""
test_audit_content_binding.py
==============================
审计内容绑定（A1 盲区修复）回归测试。

被修复的漏洞（已实测复现）
--------------------------
审计防线只校验"这个文件路径历史上出现过 APPROVED 记录"，**不校验内容**，
于是**一次旧审批**可以无限期放行该文件之后的任意改写：

    1. app.py 一年前被审计过一次 -> .pandaone/pandaone.jsonl 有
       {"status":"APPROVED","file":"app.py"}
    2. 今天把 app.py 完全改写成恶意内容（import os; os.system(...)），
       不做任何新审计
    3. git add app.py 之后：
         pre-commit hook -> exit 0（放行）
         pandaone ci     -> exit 0（"[OK] PASS - 所有变更均已审计"）

修复：审批与**内容 SHA256** 绑定
--------------------------------
  - pandaone write 落 content_sha256（= git index blob 的 SHA256，
    也就是这次提交真正要落库的内容）
  - hook / ci 取**待提交内容**的 SHA256 与之比对，不一致即拒绝
  - 存量记录（无 content_sha256）渐进增强：按路径放行 + warn
    （不能因为升级就让所有存量项目的 hook 突然拒绝所有提交）

第一性原理
----------
审计承诺是"**这一次改动**被审过"，不是"**这个路径**被审过"。
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"

MALICIOUS = "import os\nos.system('echo PWNED')\n"


# ============================================================
# helpers
# ============================================================

def _git_exe():
    git = shutil.which("git")
    if not git:
        pytest.skip("git not found")
    return git


def _env():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    env["PANDAX_LANG"] = "zh-CN"
    return env


def _git(args, cwd, check=False):
    r = subprocess.run([_git_exe()] + list(args), cwd=str(cwd), env=_env(),
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise AssertionError("git %s failed: %s" % (list(args), r.stderr))
    return r


def _git_bytes(args, cwd):
    r = subprocess.run([_git_exe()] + list(args), cwd=str(cwd), env=_env(),
                       capture_output=True)
    assert r.returncode == 0, "git %s failed: %s" % (list(args), r.stderr)
    return r.stdout


def _run_cli(*args, cwd=None):
    r = subprocess.run([sys.executable, "-m", "pandaone", *args],
                       cwd=str(cwd or ROOT_DIR), env=_env(),
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, r.stdout, r.stderr


def _setup_project(tmp_path, files=None):
    """init + git init + 初始 commit + install-hook（返回项目目录）。"""
    project = tmp_path
    rc, out, err = _run_cli("init", "--root", str(project), cwd=project)
    assert rc == 0, out + err

    # .pandaone 不入库：否则 config.json（受保护扩展名）会混进 staged 集合，
    # 让 hook/CI 的断言变成"因为别的文件违规"而不是"因为目标文件违规"。
    (project / ".gitignore").write_text(".pandaone/\n", encoding="utf-8")

    _git(["init"], project, check=True)
    _git(["config", "user.email", "t@t"], project)
    _git(["config", "user.name", "t"], project)
    for name, content in (files or {}).items():
        p = project / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    _git(["add", "-A"], project, check=True)
    _git(["commit", "-m", "init"], project, check=True)

    rc, out, err = _run_cli("install-hook", "--root", str(project), cwd=project)
    assert rc == 0, out + err
    return project


def _run_hook(project):
    """直接跑 hook 的校验脚本（cwd = 仓库根，脚本内部用 Path.cwd()）。"""
    script = project / ".pandaone" / "pre-commit-check.py"
    assert script.is_file(), "hook 校验脚本未安装"
    return subprocess.run([sys.executable, str(script)], cwd=str(project),
                          env=_env(), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _add_record(project, file, content_sha256=None, pre_sha256=None):
    """追加一条 APPROVED 审计记录（模拟 pandaone write 的落库结果）。"""
    rec = {
        "id": "audit_test_" + file.replace("/", "_").replace(".", "_"),
        "timestamp": "2026-01-01 00:00:00",
        "status": "APPROVED",
        "action": "modify",
        "file": file,
        "agent": "test",
        "reason": "unit test approval record",
        "problem": "unit test problem description",
        "approach": "unit test approach description",
        "commit_hash": "",
        "force_write": False,
        "files_changed": [file],
    }
    if content_sha256 is not None:
        rec["content_sha256"] = content_sha256
    if pre_sha256 is not None:
        rec["pre_sha256"] = pre_sha256
    path = project / ".pandaone" / "pandaone.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _read_records(project):
    path = project / ".pandaone" / "pandaone.jsonl"
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _index_sha256(project, rel):
    """index 里某路径的 blob 内容的 SHA256（= 真正要提交的内容）。"""
    return hashlib.sha256(_git_bytes(["cat-file", "blob", ":" + rel], project)).hexdigest()


# ============================================================
# 核心：hook 的内容绑定判定
# ============================================================

class TestHookContentBinding:
    """已审计文件被改写 → hook 必须拒绝（这是本次修复的核心）。"""

    def test_rewritten_audited_file_is_rejected(self, tmp_path):
        """已审计文件被完全改写 → hook 拒绝"""
        project = _setup_project(tmp_path, {"app.py": "x = 1\n"})
        _add_record(project, "app.py",
                    content_sha256=_index_sha256(project, "app.py"))

        # 完全改写成恶意内容，不做任何新审计
        (project / "app.py").write_text(MALICIOUS, encoding="utf-8")
        _git(["add", "app.py"], project)

        r = _run_hook(project)
        combined = r.stdout + r.stderr
        assert r.returncode != 0, (
            "内容被改写且未重新审计，hook 必须拒绝:\n" + combined)
        assert "app.py" in combined, "拒绝输出必须点名文件:\n" + combined

    def test_unchanged_audited_file_is_allowed(self, tmp_path):
        """已审计文件内容未变 → hook 放行（不能把正常流程堵死）"""
        project = _setup_project(tmp_path, {"app.py": "x = 1\n"})
        # 模拟"这次改动已经审过"：先把内容 add 进 index，再按 index 内容写审批
        (project / "app.py").write_text("x = 2\n", encoding="utf-8")
        _git(["add", "app.py"], project)
        _add_record(project, "app.py",
                    content_sha256=_index_sha256(project, "app.py"))

        r = _run_hook(project)
        assert r.returncode == 0, (
            "内容与审批记录一致，hook 必须放行:\n" + r.stdout + r.stderr)

    def test_reaudit_closes_the_loop(self, tmp_path):
        """改写 → 拒绝；重新审计 → 放行（闭环）"""
        project = _setup_project(tmp_path, {"app.py": "x = 1\n"})
        _add_record(project, "app.py",
                    content_sha256=_index_sha256(project, "app.py"))

        (project / "app.py").write_text("x = 2\n", encoding="utf-8")
        _git(["add", "app.py"], project)
        r1 = _run_hook(project)
        assert r1.returncode != 0, "未重新审计前必须拒绝"

        # 重新审计：新增一条绑定新内容的 APPROVED 记录
        _add_record(project, "app.py",
                    content_sha256=_index_sha256(project, "app.py"))
        r2 = _run_hook(project)
        assert r2.returncode == 0, (
            "重新审计后必须放行:\n" + r2.stdout + r2.stderr)

    def test_legacy_record_without_hash_passes_with_warning(self, tmp_path):
        """存量记录（无 content_sha256）→ 放行，但必须打 warn"""
        project = _setup_project(tmp_path, {"app.py": "x = 1\n"})
        _add_record(project, "app.py")  # 无 content_sha256

        (project / "app.py").write_text("x = 2\n", encoding="utf-8")
        _git(["add", "app.py"], project)

        r = _run_hook(project)
        combined = r.stdout + r.stderr
        assert r.returncode == 0, (
            "存量记录必须按路径放行（不能突然拒绝所有存量项目）:\n" + combined)
        assert "content_sha256" in combined, (
            "必须打印 warn 说明该审批未绑定内容:\n" + combined)

    def test_file_without_any_record_is_rejected(self, tmp_path):
        """完全没有 APPROVED 记录 → 拒绝（保持原有行为）"""
        project = _setup_project(tmp_path, {"app.py": "x = 1\n"})
        (project / "app.py").write_text("x = 2\n", encoding="utf-8")
        _git(["add", "app.py"], project)

        r = _run_hook(project)
        assert r.returncode != 0, "没有审计记录的受保护文件必须拒绝"

    def test_judgement_uses_index_not_worktree(self, tmp_path):
        """staged 与工作区不一致 → 按 index（staged）判定，而不是工作区"""
        project = _setup_project(tmp_path, {"app.py": "x = 1\n"})
        (project / "app.py").write_text("x = 2\n", encoding="utf-8")
        _git(["add", "app.py"], project)
        _add_record(project, "app.py",
                    content_sha256=_index_sha256(project, "app.py"))

        # 工作区又改了但**没有 add** —— 判定必须以 index 为准 → 放行
        (project / "app.py").write_text("x = 3\n", encoding="utf-8")
        r = _run_hook(project)
        assert r.returncode == 0, (
            "必须按 index（staged）判定，工作区未 add 的改动不影响提交:\n"
            + r.stdout + r.stderr)

    def test_judgement_uses_index_even_if_worktree_matches(self, tmp_path):
        """index 与审批不符 → 拒绝（哪怕工作区内容看起来是对的）"""
        project = _setup_project(tmp_path, {"app.py": "x = 1\n"})
        _add_record(project, "app.py",
                    content_sha256=_index_sha256(project, "app.py"))  # 绑定 x = 1

        (project / "app.py").write_text("x = 2\n", encoding="utf-8")
        _git(["add", "app.py"], project)          # index = x = 2
        (project / "app.py").write_text("x = 1\n", encoding="utf-8")  # 工作区改回

        r = _run_hook(project)
        assert r.returncode != 0, "index 内容与审批不符，必须拒绝"


# ============================================================
# 同批次小盲区
# ============================================================

class TestDotfileAndRename:
    def test_dotfile_env_is_protected(self, tmp_path):
        """dotfile（.env）必须进入检查集（旧实现 Path('.env').suffix == '' → 永远放行）"""
        project = _setup_project(tmp_path, {".env": "SECRET=1\n"})
        (project / ".env").write_text("SECRET=2\n", encoding="utf-8")
        _git(["add", ".env"], project)

        r = _run_hook(project)
        combined = r.stdout + r.stderr
        assert r.returncode != 0, (
            ".env 在受保护扩展名列表里，必须被检查:\n" + combined)
        assert ".env" in combined, "拒绝输出必须点名 .env:\n" + combined

    def test_dotfile_env_rewrite_is_rejected(self, tmp_path):
        """dotfile 的内容绑定同样生效"""
        project = _setup_project(tmp_path, {".env": "SECRET=1\n"})
        _add_record(project, ".env",
                    content_sha256=_index_sha256(project, ".env"))
        (project / ".env").write_text("SECRET=PWNED\n", encoding="utf-8")
        _git(["add", ".env"], project)

        r = _run_hook(project)
        assert r.returncode != 0, ".env 被改写后未重新审计，必须拒绝"

    def test_rename_needs_own_approval(self, tmp_path):
        """git mv 之后新路径必须独立审批（旧实现 --diff-filter=AM 漏掉 R）"""
        project = _setup_project(tmp_path, {"a.py": "x = 1\n"})
        _add_record(project, "a.py",
                    content_sha256=_index_sha256(project, "a.py"))

        _git(["mv", "a.py", "b.py"], project)
        r = _run_hook(project)
        combined = r.stdout + r.stderr
        assert r.returncode != 0, (
            "改名后的新路径必须独立审批:\n" + combined)
        assert "b.py" in combined, "拒绝输出必须点名新路径 b.py:\n" + combined


# ============================================================
# pandaone ci：内容绑定 + base 不再静默降级
# ============================================================

class TestCiContentBinding:
    def test_ci_rejects_rewritten_audited_file(self, tmp_path):
        """核心：已审计文件被完全改写 → pandaone ci 拒绝"""
        project = _setup_project(tmp_path, {"app.py": "x = 1\n"})
        _add_record(project, "app.py",
                    content_sha256=_index_sha256(project, "app.py"))
        base = _git(["rev-parse", "HEAD"], project).stdout.strip()

        (project / "app.py").write_text(MALICIOUS, encoding="utf-8")
        _git(["add", "app.py"], project)
        _git(["commit", "--no-verify", "-m", "bypass audit"], project, check=True)

        rc, out, err = _run_cli("ci", "--root", str(project), "--base", base)
        combined = out + err
        assert rc != 0, (
            "内容被改写且未重新审计，ci 必须拒绝:\n" + combined)
        assert "app.py" in combined, "ci 输出必须点名文件:\n" + combined

    def test_ci_allows_audited_content(self, tmp_path):
        """已审计且内容一致的改动 → pandaone ci 放行"""
        project = _setup_project(tmp_path, {"app.py": "x = 1\n"})
        base = _git(["rev-parse", "HEAD"], project).stdout.strip()

        (project / "app.py").write_text("x = 2\n", encoding="utf-8")
        _git(["add", "app.py"], project)
        _add_record(project, "app.py",
                    content_sha256=_index_sha256(project, "app.py"))
        _git(["commit", "--no-verify", "-m", "audited change"], project, check=True)

        rc, out, err = _run_cli("ci", "--root", str(project), "--base", base)
        assert rc == 0, (
            "内容与审批一致，ci 必须放行:\n" + out + err)

    def test_ci_legacy_record_passes_with_warning(self, tmp_path):
        """存量记录（无 content_sha256）→ ci 放行但提示"""
        project = _setup_project(tmp_path, {"app.py": "x = 1\n"})
        base = _git(["rev-parse", "HEAD"], project).stdout.strip()
        _add_record(project, "app.py")  # 无 content_sha256

        (project / "app.py").write_text("x = 2\n", encoding="utf-8")
        _git(["add", "app.py"], project)
        _git(["commit", "--no-verify", "-m", "legacy approval"], project, check=True)

        rc, out, err = _run_cli("ci", "--root", str(project), "--base", base)
        combined = out + err
        assert rc == 0, "存量记录必须放行:\n" + combined
        assert "content_sha256" in combined, "必须提示该审批未绑定内容:\n" + combined


class TestCiBaseResolution:
    def test_explicit_unresolvable_base_fails(self, tmp_path):
        """显式 --base 解析失败 → 直接 exit 1（不能静默缩小审计范围）"""
        project = _setup_project(tmp_path, {"app.py": "x = 1\n"})
        rc, out, err = _run_cli("ci", "--root", str(project),
                                "--base", "NO_SUCH_REF_XYZ")
        combined = out + err
        assert rc != 0, (
            "显式 --base 解析失败必须失败（静默降级会让审计范围被悄悄缩小）:\n"
            + combined)
        assert "NO_SUCH_REF_XYZ" in combined, "输出必须写明解析失败的 base:\n" + combined

    def test_default_base_fallback_is_reported(self, tmp_path):
        """未传 --base 时允许 fallback，但必须写明降级到了什么"""
        project = _setup_project(tmp_path, {"app.py": "x = 1\n"})
        # 制造一个"没有 main 分支、但 HEAD~1 可解析"的仓库
        _git(["branch", "-M", "feature"], project)
        (project / "extra.txt").write_text("hello\n", encoding="utf-8")
        _git(["add", "extra.txt"], project)
        _git(["commit", "-m", "second"], project, check=True)

        rc, out, err = _run_cli("ci", "--root", str(project))
        combined = out + err
        assert "HEAD~1" in combined, (
            "未指定 --base 时的降级必须写明降级到了什么:\n" + combined)


# ============================================================
# pandaone write：审计记录必须带内容哈希
# ============================================================

class TestWriteRecordsContentHash:
    def test_write_records_content_sha256(self, tmp_path):
        """pandaone write 必须把内容哈希写进审计记录"""
        project = _setup_project(tmp_path, {"app.py": "x = 1\n"})
        rc, out, err = _run_cli(
            "write", "--root", str(project), "--file", "app.py",
            "--reason", "测试内容哈希绑定",
            "--problem", "确认 write 会把 content_sha256 写进审计记录",
            "--approach", "调用 pandaone write 修改文件，然后检查审计记录内容",
            "--old", "x = 1", "--new", "x = 2",
            cwd=project,
        )
        assert rc == 0, out + err

        recs = [r for r in _read_records(project) if r.get("file") == "app.py"]
        assert recs, "审计日志里应有 app.py 的记录"
        last = recs[-1]
        assert last.get("content_sha256"), "审计记录必须带 content_sha256"
        committed = _git_bytes(["cat-file", "blob", "HEAD:app.py"], project)
        assert last["content_sha256"] == hashlib.sha256(committed).hexdigest(), (
            "content_sha256 必须是**真正落库内容**的哈希")
        assert last.get("pre_sha256"), "审计记录应带 pre_sha256（改写前原内容哈希）"

    def test_write_then_rewrite_is_rejected_by_hook(self, tmp_path):
        """write 之后再次改写 → hook 拒绝（端到端闭环）"""
        project = _setup_project(tmp_path, {"app.py": "x = 1\n"})
        rc, out, err = _run_cli(
            "write", "--root", str(project), "--file", "app.py",
            "--reason", "端到端闭环测试",
            "--problem", "确认 write 之后的改写会被 hook 拦下",
            "--approach", "先 write 一次，再手工改写并 add，然后跑 hook",
            "--old", "x = 1", "--new", "x = 2",
            cwd=project,
        )
        assert rc == 0, out + err

        (project / "app.py").write_text(MALICIOUS, encoding="utf-8")
        _git(["add", "app.py"], project)
        r = _run_hook(project)
        assert r.returncode != 0, (
            "write 之后又改写，hook 必须拒绝:\n" + r.stdout + r.stderr)


# ============================================================
# hook 与 ci 共用同一套判定（防止实现漂移）
# ============================================================

class TestSharedBindingModule:
    def test_hook_template_uses_package_binding_module(self):
        """hook 模板必须复用主包的判定模块（同一份实现，不允许两处漂移）"""
        import importlib.util

        import pandaone.audit_binding as ab

        tpl = SRC_DIR / "pandaone" / "templates" / "pre-commit-check.py"
        spec = importlib.util.spec_from_file_location("tpl_pre_commit_check", str(tpl))
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        loaded = mod._load_binding()
        assert loaded is not None, "hook 模板必须能加载共享判定模块"
        assert Path(loaded.__file__).resolve() == Path(ab.__file__).resolve(), (
            "hook 模板与 pandaone ci 必须指向同一份 audit_binding.py")

    def test_install_hook_copies_binding_module(self, tmp_path):
        """install-hook 必须把共享判定模块拷到 .pandaone/（hook 是独立副本）"""
        import pandaone.audit_binding as ab

        project = _setup_project(tmp_path, {"app.py": "x = 1\n"})
        copied = project / ".pandaone" / "audit_binding.py"
        assert copied.is_file(), "install-hook 必须把 audit_binding.py 拷到 .pandaone/"
        assert copied.read_bytes() == Path(ab.__file__).read_bytes(), (
            "拷贝的必须是同一份文件（字节级一致）")

    def test_verify_content_semantics(self):
        """共享判定函数的语义（纯单元测试）"""
        from pandaone import audit_binding as ab

        records = [
            {"status": "APPROVED", "file": "a.py"},
            {"status": "APPROVED", "file": "b.py", "content_sha256": "AA"},
            {"status": "REJECTED", "file": "c.py", "content_sha256": "CC"},
        ]
        # 无记录 → no_record
        assert ab.verify_content("x.py", b"data", records)["status"] == ab.STATUS_NO_RECORD
        # 老记录 → legacy（按路径放行）
        assert ab.verify_content("a.py", b"data", records)["status"] == ab.STATUS_LEGACY
        # 有哈希且一致 → ok
        good = [{"status": "APPROVED", "file": "d.py",
                 "content_sha256": ab.sha256_bytes(b"data")}]
        assert ab.verify_content("d.py", b"data", good)["status"] == ab.STATUS_OK
        # 有哈希但不一致 → mismatch
        assert ab.verify_content("d.py", b"evil", good)["status"] == ab.STATUS_MISMATCH
        # REJECTED 记录不算数
        assert ab.verify_content("c.py", b"data", records)["status"] == ab.STATUS_NO_RECORD

    def test_effective_suffix_handles_dotfiles(self):
        """dotfile 感知的有效后缀（与 _effective_suffix 同语义）"""
        from pandaone import audit_binding as ab

        assert ab.effective_suffix("main.py") == ".py"
        assert ab.effective_suffix(".env") == ".env"
        assert ab.effective_suffix(".env.local") == ".local"
        assert ab.effective_suffix(".gitignore") == ".gitignore"
        assert ab.effective_suffix("noext") == ""
        assert ab.effective_suffix("dir.py/file") == ""
