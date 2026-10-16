# -*- coding: utf-8 -*-
# P0-4 验证: export_yaml 头部 version 用 __version__, 不再写死 0.1.0
# 关键: 删 sys.modules['pandaone*'] cache, 让 src/pandaone/__init__.py 重新加载
#  (site-packages 0.7.14 装的 pandaone 会占用 cache, 但 src/pandaone_guard.egg-info 0.7.18 是 single source of truth)
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / 'src'
# 删 site-packages pandaone cache (0.7.14 装的)
for _k in list(sys.modules.keys()):
    if _k == 'pandaone' or _k.startswith('pandaone.'):
        del sys.modules[_k]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from pandaone import __version__
from pandaone.exporters import export_yaml


def test_export_yaml_uses_runtime_version():
    record = {'id': 't1', 'status': 'APPROVED'}
    with tempfile.NamedTemporaryFile(suffix='.yaml', delete=False, mode='w') as f:
        path = Path(f.name)
    try:
        export_yaml([record], path)
        text = path.read_text(encoding='utf-8')
        assert '0.1.0' not in text, f'export_yaml 仍写死 0.1.0, 内容={text!r}'
        assert __version__ in text, f'export_yaml 没引用 __version__(={__version__!r}), 内容={text!r}'
    finally:
        if path.exists():
            path.unlink()


def test_exporters_module_top_level_imports_version():
    src = (_SRC / 'pandaone' / 'exporters.py').read_text(encoding='utf-8')
    assert 'from . import __version__' in src, 'exporters.py 顶部缺少 __version__ import'
    assert '0.1.0' not in src, f'exporters.py 仍有 0.1.0 字面量, 全文={src!r}'


if __name__ == '__main__':
    test_export_yaml_uses_runtime_version()
    test_exporters_module_top_level_imports_version()
    print('OK C1 验证全过')
