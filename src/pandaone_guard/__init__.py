"""
pandaone_guard — Pandaone AI Agent L2 防御守护进程

入口:
  - python -m pandaone_guard --root <project>
  - python -m pandaone_guard --root <project> --daemon
"""

# v0.7.22 P1-2 fix: 版本号单一来源。
# 之前这里硬编码 "0.1.0", 而 pyproject.toml 是 0.7.21.3 —— 同一个项目两个版本号,
# 导出的合规报告元数据可能因此写错版本。委托给 pandaone.__version__ 解析
# (importlib.metadata → pyproject.toml → 兜底, 见 pandaone/__init__.py)。
try:
    from pandaone import __version__ as _pandaone_version
    __version__ = _pandaone_version
except Exception:  # pragma: no cover - pandaone 不可用时的兜底
    try:
        from importlib.metadata import version as _v, PackageNotFoundError as _PNFE
        try:
            __version__ = _v("pandaone-guard")
        except _PNFE:
            __version__ = "0.0.0+unknown"
    except Exception:
        __version__ = "0.0.0+unknown"

from .__main__ import main, run_watchdog, PandaXHandler

__all__ = ["main", "run_watchdog", "PandaXHandler", "__version__"]