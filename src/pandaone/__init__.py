"""
Pandaone AI Agent — AI Agent 代码审计门禁系统

主包入口:
  - CLI:    pandaone <command> [args]
  - Module: python -m pandaone <command> [args]
  - API:    from pandaone import main; main()

第一性原理:
  - pip install 后立即可用，无须配置 PYTHONPATH
  - 与 Hermes 等成熟 Python CLI 的分发模式对齐
  - 跨平台: Windows / Linux / macOS
  - 版本号单一事实源: pyproject.toml → METADATA → importlib.metadata
    (避免硬编码字面量与 pyproject.toml 漂移)
"""

# ---------------------------------------------------------------------------
# 版本号: 单一事实源
#   - 已安装(pip install *.whl): importlib.metadata.version("pandaone-guard")
#   - 源码树(开发模式 / 源码直跑): 仓库根的 pyproject.toml [project].version
#   - 极端 fallback: 字面量常量(打包脚本异常时仍可启动 CLI)
#
# v0.7.22 fix: 源码树模式下**优先**用 pyproject.toml。
#   原来无论哪种模式都先取包元数据, 于是源码树里跑时拿到的是**上次安装**的版本
#   (装的是 0.7.21.3, 源码已改成 0.7.22.0), 造成两个后果:
#     1. 版本号漂移: import pandaone 报 0.7.21.3, pyproject 却是 0.7.22.0
#        (report P1-2 说的就是这类不一致)
#     2. L5 指纹锁死: 指纹按 {version, hash} 绑定, 版本不变 + 源码变了
#        → 被判成"篡改" → 所有子命令 exit 1 (report P0-4c 的同一类问题)
# ---------------------------------------------------------------------------


def _resolve_version() -> str:
    """解析当前版本号。单一事实源见上方注释。"""
    import re as _re
    import sys as _sys
    from pathlib import Path as _Path

    # PyInstaller frozen (打包成 .exe)：仓库根的 pyproject.toml 不在包里，
    # importlib.metadata 也读不到（没有安装元数据）→ 版本号会退化成
    # "0.0.0+unknown"。解法：打包时把版本号注入 pandaone/_build_info.py。
    if getattr(_sys, "_MEIPASS", None):
        try:
            from pandaone import _build_info  # type: ignore[attr-defined]

            _bv = getattr(_build_info, "__version__", None)
            if _bv:
                return str(_bv)
        except Exception:
            pass
        try:
            _p = _Path(_sys._MEIPASS) / "pandaone" / "_build_info.py"
            _m = _re.search(r'__version__\s*=\s*"([^"]+)"',
                            _p.read_text(encoding="utf-8"))
            if _m:
                return _m.group(1)
        except Exception:
            pass

    _root = _Path(__file__).resolve().parent.parent.parent  # 仓库根 或 site-packages
    _toml_path = _root / "pyproject.toml"
    # 源码树里有 pyproject.toml, 已安装的 wheel 里没有 → 天然的模式判别
    _in_source_tree = _toml_path.is_file()

    # 无论哪种模式都先问一次 metadata（保持既有调用约定）
    _meta_version = None
    try:
        from importlib.metadata import version as _v
        try:
            _meta_version = _v("pandaone-guard")
        except Exception:
            _meta_version = None
    except ImportError:  # Python < 3.8 兜底（理论上不支持）
        _meta_version = None

    def _from_pyproject():
        try:
            _m = _re.search(
                r'^\s*version\s*=\s*"([^"]+)"\s*$',
                _toml_path.read_text(encoding="utf-8"),
                _re.MULTILINE,
            )
            return _m.group(1) if _m else None
        except Exception:
            return None

    if _in_source_tree:
        _v_py = _from_pyproject()
        if _v_py:
            return _v_py
    if _meta_version:
        return _meta_version
    _v_py = _from_pyproject()
    if _v_py:
        return _v_py
    return "0.0.0+unknown"


__version__ = _resolve_version()

from .cli import main

__all__ = ["main", "__version__"]
