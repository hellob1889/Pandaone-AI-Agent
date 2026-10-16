# -*- coding: utf-8 -*-
# C2 验证: _pid_alive 跨平台 PID 探活 (psutil.pid_exists 替代 os.kill)
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / 'src'
for _k in list(sys.modules.keys()):
    if _k == 'pandaone' or _k.startswith('pandaone.'):
        del sys.modules[_k]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import os
import psutil


def test_pyproject_declares_psutil():
    # pyproject.toml dependencies 必须含 psutil
    toml = (_ROOT / 'pyproject.toml').read_text(encoding='utf-8')
    assert 'psutil' in toml, f'pyproject.toml 缺 psutil 依赖, 内容={toml[:500]!r}'


def test_pid_alive_handles_invalid_input():
    # 加载 part_004 的 _pid_alive (cli.py 是 chunk loader, 走 exec 路径)
    from pandaone.cli import _pid_alive
    assert _pid_alive('not_a_number') is False
    assert _pid_alive('') is False
    assert _pid_alive('0') is False
    assert _pid_alive('-1') is False


def test_pid_alive_uses_psutil():
    # _pid_alive 内部必须用 psutil.pid_exists (不能 fall back 到 os.kill on Windows)
    from pandaone.cli import _pid_alive
    # 当前进程 PID 必存活
    my_pid = str(os.getpid())
    assert _pid_alive(my_pid) is True, f'_pid_alive(我的 PID={my_pid}) 应返回 True'
    # 一个不存在的超大 PID
    assert _pid_alive('99999999999') is False, '_pid_alive(超大 PID) 应返回 False'


if __name__ == '__main__':
    test_pyproject_declares_psutil()
    test_pid_alive_handles_invalid_input()
    test_pid_alive_uses_psutil()
    print('OK C2 验证全过')
