# -*- coding: utf-8 -*-
# C7-2 验证: cmd_watch daemon Popen 启动 pandaone_guard 时传 --daemon flag
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / 'src'
for _k in list(sys.modules.keys()):
    if _k == 'pandaone' or _k.startswith('pandaone.'):
        del sys.modules[_k]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def test_watch_daemon_popen_includes_daemon_flag():
    # 静态校验: part_005.py cmd_watch daemon 分支的 Popen cmd 列表含 --daemon
    src = (_ROOT / 'src' / 'pandaone' / 'cli_chunks' / 'part_005.py').read_text(encoding='utf-8')
    # 找 cmd_watch daemon 分支 (if getattr(args, 'daemon', False): 后面)
    start = src.find('if getattr(args, "daemon", False):')
    assert start > 0, 'cmd_watch daemon 分支未找到'
    daemon_block = src[start:start + 2000]  # 取 daemon 分支 2000 字符
    # frozen (pandaone_guard.exe) 和 non-frozen 两条 cmd 都应含 --daemon
    exe_cmd_idx = daemon_block.find('pandaone_guard.exe')
    mod_cmd_idx = daemon_block.find('-m')
    assert exe_cmd_idx > 0, 'frozen cmd 未找到'
    assert mod_cmd_idx > 0, 'non-frozen cmd 未找到'
    # 两条 cmd 后 200 字符内必须有 '--daemon'
    exe_section = daemon_block[exe_cmd_idx:exe_cmd_idx + 200]
    mod_section = daemon_block[mod_cmd_idx:mod_cmd_idx + 200]
    assert '--daemon' in exe_section, f'frozen cmd 漏传 --daemon:\n{exe_section}'
    assert '--daemon' in mod_section, f'non-frozen cmd 漏传 --daemon:\n{mod_section}'


def test_pandaone_guard_supports_daemon_flag():
    # 静态校验: pandaone_guard.__main__ 接受 --daemon flag
    guard_main = (_ROOT / 'src' / 'pandaone_guard' / '__main__.py').read_text(encoding='utf-8')
    assert 'daemon' in guard_main, 'pandaone_guard.__main__ 不处理 daemon flag'


if __name__ == '__main__':
    test_watch_daemon_popen_includes_daemon_flag()
    test_pandaone_guard_supports_daemon_flag()
    print('OK C7-2 验证全过')
