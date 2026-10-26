r"""
conftest.py
===========
pytest 全局配置：自动探测 git 路径并加入 PATH。

第一性原理：
  - git 是 Pandaone AI Agent 的关键依赖（用于自动 commit）
  - 用户可能 git 装在非默认路径
  - 测试不应假设 git 在 PATH 中

策略：
  - 探测常见 git 安装路径（来自 pandaone.git_installer._windows_candidate_dirs 单一来源）
  - 找到第一个存在的 git.exe 加到 PATH
  - 测试用 subprocess 启动时就会继承此 PATH

Bug #40 fix (v0.7.10): 不再硬编码 `D:\软件\Git\cmd` 等作者机器路径，
统一从 git_installer._windows_candidate_dirs() 派生。

v0.7.31.0: 首行改用 raw string（r 前缀 + 三引号）。上面的 `D:\软件\Git\cmd` 含 `\G`
这类非法转义序列，Python 3.12+ 会抛 DeprecationWarning 并在将来变成 SyntaxError。
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# ============================================================
# v0.7.22: src/ 必须**最先**进 sys.path。
#
# 原来这段注入排在文件第 62 行，位置太靠后：上面第 30 行的
# `from pandaone.git_installer import ...` 已经把 pandaone 包导进
# sys.modules，之后 `from pandaone import cli` 拿到的就是 site-packages
# 里已安装的旧副本，不是工作区源码。
# 后果：改完源码跑测试，测的却不是改的东西 —— 测试全绿也说明不了问题。
# （也解释了 report 里 test_installed_metadata_consistency 被静默跳过：
#  它比较的就是 site-packages，而那里没有 pandaone-guard 的元数据。）
#
# 所以注入必须排在任何 pandaone 导入之前。
# ============================================================
ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
# PYTHONPATH 让 subprocess 继承（开发模式下 `python -m pandaone_guard` 能找到）
os.environ["PYTHONPATH"] = str(SRC_DIR) + os.pathsep + os.environ.get("PYTHONPATH", "")

# 常见 git 安装位置（Windows）— 单一来源 = pandaone.git_installer._windows_candidate_dirs
# 兼容 pandaone 还没完全 import 的早期阶段（pytest 收集阶段），用 try/except 兜底
try:
    from pandaone.git_installer import _windows_candidate_dirs as _git_windows_dirs
    GIT_CANDIDATES = _git_windows_dirs()
except Exception:
    # 兜底：极端情况下 pandaone 不可用，使用最小硬编码候选（仅标准位置，无作者路径）
    GIT_CANDIDATES = [
        r"C:\Program Files\Git\cmd",
        r"C:\Program Files (x86)\Git\cmd",
        r"C:\Program Files\Git\bin",
        r"C:\Git\cmd",
    ]


def _find_git_dir() -> str | None:
    """返回第一个含 git.exe 的目录"""
    # 1. 先看 PATH 里有没有
    if shutil.which("git"):
        return None  # 已在 PATH，不动
    # 2. 探测候选路径
    for cand in GIT_CANDIDATES:
        if Path(cand, "git.exe").exists():
            return cand
    # 3. 用 where.exe 兜底
    try:
        r = subprocess.run(["where.exe", "git"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            first = r.stdout.strip().splitlines()[0]
            return str(Path(first).parent)
    except Exception:
        pass
    return None


# 把 src/ 加到 sys.path 和 PYTHONPATH 的逻辑已上移到文件顶部（见上方 v0.7.22 说明），
# 必须在任何 `import pandaone` 之前完成。


# 模块导入时立即把 git 加入 PATH
_git_dir = _find_git_dir()
if _git_dir:
    os.environ["PATH"] = _git_dir + os.pathsep + os.environ.get("PATH", "")


@pytest.fixture(scope="session", autouse=True)
def verify_git_available():
    """全局 fixture：测试开始前确认 git 可用，否则 skip"""
    if not shutil.which("git"):
        pytest.skip("git 未安装且未在 PATH 中找到，Pandaone 测试需要 git")


@pytest.fixture(scope="session", autouse=True)
def reseed_fingerprint_for_session():
    """session 开始时把指纹重播种为**当前源码**的正确指纹。

    第一性原理：
      - 指纹文件 `~/.pandaone_fp.txt` 是**跨进程的全局状态**，不是测试产物。
      - 判定顺序里「同版本 + hash 变」= 判篡改 -> CLI 锁死（rc=1）。
      - 所以上一次运行留下的记录（版本号/hash 与当前源码不符）会让本次运行
        大批**无关**测试连环失败 —— 实测：改完版本号后第一次全量跑挂了 32 个，
        第二次就全绿。纯脏状态问题，不是代码问题。
      - 反过来也一样：上次跑的是 frozen 形态（form=frozen），这次跑源码形态，
        形态不符虽会自动刷新，但前提是版本也变了；版本相同就是锁死。

    为什么只在 session 开始做一次：
      - `compute_fingerprint()` 要扫整个包目录做 manifest，per-test 跑太慢。
      - session 级足以消除「上次运行残留」这一类脏状态。

    副作用说明：
      - 测完留在用户机器上的记录 = 当前源码版本 + source 形态。
        这与「用户平时就在源码树里跑 pandaone」的真实状态一致，不算污染。
      - 指纹文件被清掉也不影响：首次运行会自动重新生成。
    """
    try:
        from pandaone import fp_security as _fpsec
        from pandaone import __version__ as _ver
        _fpsec.save_fp(str(_ver), _fpsec.compute_fingerprint())
    except Exception:
        # 播种失败不该让整个测试会话挂掉 —— 顶多让个别测试失败
        pass


@pytest.fixture(autouse=True)
def force_zh_cn_for_tests(request):
    """全局 fixture（function-scope）：每个测试前后强制 ~/.pandaone/config.json lang=zh-CN。

    第一性原则（对抗式审查）：
      - 测试断言中包含中文字符串（如 '已安装'、'锁定'、'未运行'）。
      - test_i18n.py 多处调 i18n.set_lang("en") / _save_user_pref("en") 污染 config.json。
      - 早期实现用 session-scope，只在首尾各设一次，导致中途被污染后所有后续测试 flaky。
      - 改为 function-scope + 前后双保险，确保每个测试看到 lang=zh-CN。

    实现策略：
      - setup：读取 backup，强制写入 lang=zh-CN
      - yield
      - teardown：恢复 backup（无论测试是否改了 lang）

    性能：~200 测试 × 1ms 文件 IO = 0.2s，可接受。
    """
    cfg_path = Path.home() / ".pandaone" / "config.json"
    backup_existed = cfg_path.exists()
    backup_text = None
    if backup_existed:
        try:
            backup_text = cfg_path.read_text(encoding="utf-8")
        except Exception:
            backup_text = None

    def _set_zh_cn():
        try:
            if backup_text is not None:
                cfg = json.loads(backup_text)
            else:
                cfg = {}
            cfg["lang"] = "zh-CN"
            cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    _set_zh_cn()
    yield

    # teardown：恢复原始内容（如果测试期间被改成 en，下次测试前 setup 会再设回 zh-CN；
    # 但用户希望测完后状态也恢复，所以这里也写回原始 backup）
    if backup_existed and backup_text is not None:
        try:
            cfg_path.write_text(backup_text, encoding="utf-8")
        except Exception:
            pass
    elif not backup_existed and cfg_path.exists():
        # 用户原本没有 config.json，但测试创建了——保守起见保留（避免破坏用户数据）
        pass
