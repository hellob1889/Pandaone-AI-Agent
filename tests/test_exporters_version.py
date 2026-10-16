# -*- coding: utf-8 -*-
# P0-4 验证: export_yaml 头部 version 用 __version__, 不再写死 0.1.0
# 用 # 注释代替 docstring, 绕开 pandaone write argparse unquote 截断
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from pandaone import __version__
from pandaone.exporters import export_yaml


def test_export_yaml_uses_runtime_version():
    # 准备 1 条最小 record, 走 export_yaml 实际生成 yaml 文件
    record = {'id': 't1', 'status': 'APPROVED'}
    with tempfile.NamedTemporaryFile(suffix='.yaml', delete=False, mode='w') as f:
        path = Path(f.name)
    try:
        export_yaml([record], path)
        text = path.read_text(encoding='utf-8')
        # 旧字面量 0.1.0 一定不再出现
        assert '0.1.0' not in text, f'export_yaml 仍写死 0.1.0 字面量, 内容={text!r}'
        # 新引用 __version__ 出现 (用单引号字符串里嵌入运行时版本号)
        assert __version__ in text, f'export_yaml 没引用 __version__, 内容={text!r}'
    finally:
        if path.exists():
            path.unlink()


def test_exporters_module_top_level_imports_version():
    # 静态校验: exporters.py 顶部 from . import __version__ 真实存在
    src = (_SRC / 'pandaone' / 'exporters.py').read_text(encoding='utf-8')
    assert 'from . import __version__' in src, 'exporters.py 顶部缺少 __version__ import'
    # 0.1.0 字面量已完全替换
    assert '0.1.0' not in src, f'exporters.py 仍有 0.1.0 字面量, 全文={src!r}'


if __name__ == '__main__':
    test_export_yaml_uses_runtime_version()
    test_exporters_module_top_level_imports_version()
    print('OK C1 验证全过')
