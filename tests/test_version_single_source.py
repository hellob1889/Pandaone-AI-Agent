"""
Bug Fix #TBD (新发现的 bug): 版本号漂移

问题:
  - pyproject.toml 的 version 字段是 0.7.1
  - 但 src/pandaone/__init__.py 里的 __version__ 字面量是 0.7.0
  - 导致 wheel 里也是 0.7.0,pip show 和 import 不一致
  - 用户从 pip 装的包,运行时报告的是旧版本

第一性原理:
  - 版本号必须单一事实源 (Single Source of Truth)
  - 推荐: pyproject.toml → METADATA → importlib.metadata.version()
  - 兜底: 直接读 pyproject.toml

测试范围:
  1. import pandaone; pandaone.__version__ 必须能从 importlib.metadata 取到
  2. __version__ 必须等于 pyproject.toml 的 version 字段
  3. 必须不存在硬编码字面量 "0.7.0" 之类(只允许 importlib.metadata 拿)
"""

import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
INIT_PY = REPO_ROOT / "src" / "pandaone" / "__init__.py"


def _read_pyproject_version() -> str:
    text = PYPROJECT.read_text(encoding="utf-8")
    m = re.search(r'^\s*version\s*=\s*"([^"]+)"\s*$', text, re.MULTILINE)
    assert m, "pyproject.toml 缺少 [project].version 字段"
    return m.group(1)


def _read_init_source() -> str:
    return INIT_PY.read_text(encoding="utf-8")


class TestVersionSingleSource:
    def test_pyproject_version_exists(self):
        v = _read_pyproject_version()
        assert re.match(r"^\d+\.\d+\.\d+", v), f"version 格式不规范: {v}"

    def test_import_version_matches_pyproject(self):
        """import pandaone; pandaone.__version__ == pyproject.toml version"""
        # 确保 src 在 path 上(开发模式)
        src = str(REPO_ROOT / "src")
        if src not in sys.path:
            sys.path.insert(0, src)
        import pandaone

        pkg_version = pandaone.__version__
        pyproject_version = _read_pyproject_version()

        assert pkg_version == pyproject_version, (
            f"版本号漂移! importlib.metadata / 兜底读取得到 {pkg_version!r}, "
            f"但 pyproject.toml 是 {pyproject_version!r}"
        )

    def test_no_hardcoded_literal_version(self):
        """__init__.py 不允许出现 __version__ = "硬编码" 这种字面量赋值"""
        src = _read_init_source()
        # 匹配形如: __version__ = "0.x.y" (排除带 + 后缀的兜底占位符)
        bad = re.findall(r'__version__\s*=\s*"(\d+\.\d+\.\d+(?!\+)[^"]*)"', src)
        assert not bad, (
            f"检测到硬编码 __version__ 字面量: {bad}\n"
            "必须使用 importlib.metadata 或 pyproject.toml 动态读取"
        )

    def test_installed_metadata_consistency(self):
        """若已安装, pip show / import.__version__ 应一致"""
        try:
            from importlib.metadata import version as _v, PackageNotFoundError
        except ImportError:
            return  # Python < 3.8

        try:
            installed = _v("pandaone-guard")
        except PackageNotFoundError:
            return  # 未安装,跳过

        src = str(REPO_ROOT / "src")
        if src not in sys.path:
            sys.path.insert(0, src)
        # v0.7.22 fix: 原来 del sys.modules["pandaone"] 再 import，
        #   会造出**新的模块对象**，让其他模块持有的旧引用失效
        #   （后续测试的 patch("pandaone.xxx") 会打到新对象上，mock 静默失效）。
        #   改用 importlib.reload：复用同一模块对象、重新执行 __init__.py。
        import importlib
        import pandaone
        importlib.reload(pandaone)

        # 如果当前进程的 import 是从 site-packages 来的,直接比较
        # 如果是开发模式 (src/),则忽略 import 的版本,以 METADATA 为准
        from pathlib import Path as _P

        site_file = _P(pandaone.__file__).resolve()
        sitepackages_match = "site-packages" in str(site_file)

        if sitepackages_match:
            assert installed == pandaone.__version__, (
                f"METADATA ({installed}) 与运行时 __version__ ({pandaone.__version__}) 不一致"
            )

    def test_dev_mode_fallback_reads_pyproject(self):
        """源码模式(未安装)应能从 pyproject.toml 兜底读出版本"""
        src = str(REPO_ROOT / "src")
        if src not in sys.path:
            sys.path.insert(0, src)
        # 模拟未安装: 把 pandaone.dist-info 路径藏起来不容易
        # 这里改为: 临时覆盖 importlib.metadata.version 让其抛 PackageNotFoundError
        import importlib.metadata as im
        from unittest import mock

        with mock.patch.object(
            im, "version", side_effect=im.PackageNotFoundError("pandaone-guard")
        ) as metadata_version:
            # v0.7.22 fix: 改用 importlib.reload 而非 del sys.modules + import，
            #   避免制造模块对象分裂（详见上方注释）。
            import importlib
            import pandaone
            importlib.reload(pandaone)

            metadata_version.assert_called_once_with("pandaone-guard")
            assert pandaone.__version__ == _read_pyproject_version(), (
                f"源码兜底模式读取到 {pandaone.__version__!r}, "
                f"应等于 pyproject.toml: {_read_pyproject_version()!r}"
            )
