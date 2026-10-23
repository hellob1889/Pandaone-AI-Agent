# -*- coding: utf-8 -*-
"""
test_context_menu_registry.py — P0-1 回归测试：Windows 右键菜单注册表结构
============================================================================

背景 (v0.7.22 修复):
  v0.7.9 ~ v0.7.21.3 写的是
      SubCommands = "shell\\Init;shell\\Lock;..."  +  <base>\\shell\\<name>\\open\\command
  Explorer 对此**静默不显示整个级联菜单**（100% 复现，不报错、不写日志）。

  实测方式：Shell.Application 的 item.Verbs() 直接问 Explorer 到底有哪些动词。
      SubCommands + open\\command   → 不显示   (v0.7.20 的修复方案, 实测无效)
      SubCommands + command         → 不显示
      ExtendedSubCommandsKey + command → 显示 ✅

  根因：MS 文档 "How to Create Cascading Menus with the SubCommands Registry Entry"
  要求自定义静态动词实现在
      HKLM\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\CommandStore\\Shell\\<Verb>\\command
  即 SubCommands 方案依赖 **HKLM（需管理员）**，HKCU 用户级注册不进去，
  Explorer 直接把级联菜单判为空 → 隐藏。
  ExtendedSubCommandsKey 指向 HKCU 内相对路径，普通用户即可用。

  另外：不要再加 "open" 中间层。"open" 是动词名（系统默认动词就是
  shell\\open\\command），放在 verb 下面会被当成子动词，Explorer 反而不认。

本测试锁死三条不变量：
  1. 必须写 ExtendedSubCommandsKey = "Pandaone\\Shell"
  2. verb 命令必须写在 <base>\\Shell\\<name>\\command（不带 open 中间层）
  3. 不得写 SubCommands 值（空串或列表都会让 Explorer 隐藏菜单）

为什么以前没被发现：
  整个 tests/ 没有任何一处调用过 winreg.OpenKey / CreateKey，
  装完只信 CreateKey 没抛异常 —— 写了但 Explorer 认不出，一样打印"安装完成"。
"""
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pandaone import cli  # noqa: E402


class _FakeKey:
    """winreg key 对象替身（支持 with 语法）。"""

    def __init__(self, store, path):
        self._store = store
        self._path = path

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def SetValueEx(self, key, name, reserved, vtype, value):
        self._store.values.setdefault(self._path, {})[name] = value

    def CloseKey(self):
        pass


def _module_SetValueEx(key, name, reserved, vtype, value):
    """winreg.SetValueEx(key, ...) 是模块级函数, key 对象由 CreateKey 返回。"""
    key._store.values.setdefault(key._path, {})[name] = value


class _FakeStore:
    """记录所有写入的 (path -> {value_name: value}) 与删除的 path。"""

    def __init__(self):
        self.values = {}
        self.deleted = []

    def CreateKey(self, hive, path):
        self.values.setdefault(path, {})
        return _FakeKey(self, path)

    def OpenKey(self, hive, path):
        if path not in self.values:
            raise FileNotFoundError(path)
        return _FakeKey(self, path)

    def QueryValueEx(self, key, name):
        try:
            return key._store.values[key._path][name], 1
        except KeyError:
            raise FileNotFoundError(name)

    def DeleteKey(self, hive, path):
        self.deleted.append(path)
        if path in self.values:
            del self.values[path]
        else:
            raise FileNotFoundError(path)

    def DeleteValue(self, key, name):
        key._store.values.get(key._path, {}).pop(name, None)


def _make_fake_winreg():
    """构造一个可以塞进 sys.modules 的 winreg 替身。"""
    module = types.ModuleType("winreg")
    store = _FakeStore()
    module.HKEY_CURRENT_USER = "HKCU"
    module.REG_SZ = 1
    module.CreateKey = store.CreateKey
    module.OpenKey = store.OpenKey
    module.QueryValueEx = store.QueryValueEx
    module.DeleteKey = store.DeleteKey
    module.DeleteValue = store.DeleteValue
    module.SetValueEx = _module_SetValueEx
    module.CloseKey = lambda key: None
    module.store = store
    return module, store


@pytest.fixture
def fake_registry(monkeypatch):
    """注入 winreg 替身 + 固定 exe 路径，返回 store。"""
    module, store = _make_fake_winreg()
    monkeypatch.setitem(sys.modules, "winreg", module)
    monkeypatch.setattr(
        cli, "_find_pandaone_exe_windows", lambda: r"C:\fake\pandaone.exe"
    )
    return store


def _install(fake_registry):
    rc = cli._windows_registry_install("install", force=True)
    assert rc == 0, "install 返回码非 0"
    return fake_registry


def test_writes_extended_subcommands_key(fake_registry):
    """不变量 1: 父键必须写 ExtendedSubCommandsKey（不是 SubCommands）。"""
    _install(fake_registry)
    for base in cli.BASE_KEYS:
        values = fake_registry.values.get(base, {})
        assert values.get("ExtendedSubCommandsKey") == r"Pandaone\Shell", (
            f"{base} 缺少正确的 ExtendedSubCommandsKey, 实际: {values!r}"
        )


def test_never_writes_subcommands(fake_registry):
    """不变量 3: SubCommands 方案依赖 HKLM, HKCU 写了也白写，必须不写。"""
    _install(fake_registry)
    for base in cli.BASE_KEYS:
        values = fake_registry.values.get(base, {})
        assert "SubCommands" not in values, (
            f"{base} 仍写了 SubCommands={values.get('SubCommands')!r}, "
            "Explorer 会判 0 子菜单并隐藏整个菜单"
        )


def test_verb_command_under_shell_key(fake_registry):
    """不变量 2: verb 命令在 <base>\\Shell\\<name>\\command。"""
    _install(fake_registry)
    for base in cli.BASE_KEYS:
        for name, _label, action_cmd in cli.SUB_COMMANDS:
            cmd_path = f"{base}\\Shell\\{name}\\command"
            assert cmd_path in fake_registry.values, f"缺少 {cmd_path}"
            cmd = fake_registry.values[cmd_path][""]
            assert action_cmd in cmd, f"{cmd_path} 的命令串不含 {action_cmd}: {cmd}"
            # 回归防护: 右键菜单不应带 --trust-default (会静默关掉 L5 自校验)
            assert "--trust-default" not in cmd, (
                f"{cmd_path} 仍带 --trust-default, 右键入口会静默绕过完整性校验"
            )


def test_no_open_intermediate_layer(fake_registry):
    """open 是动词名不是中间层，写 <verb>\\open\\command 反而让 Explorer 不认。"""
    _install(fake_registry)
    for path in fake_registry.values:
        assert "\\open\\command" not in path, (
            f"出现 open 中间层 {path}, Explorer 不认这种结构"
        )


def test_self_check_reads_back_new_structure(fake_registry):
    """装后自检必须按新结构回读，否则自检形同虚设。"""
    _install(fake_registry)
    # 自检成功说明 install 返回 0；再验证每个 base 的 verb 都能被读回
    for base in cli.BASE_KEYS:
        assert fake_registry.values[base]["ExtendedSubCommandsKey"] == r"Pandaone\Shell"
        for name, _label, _cmd in cli.SUB_COMMANDS:
            assert f"{base}\\Shell\\{name}\\command" in fake_registry.values


def test_uninstall_removes_new_and_legacy_paths(fake_registry):
    """卸载必须同时清掉新结构和 v0.7.20 及更早的历史遗留键。"""
    _install(fake_registry)
    fake_registry.deleted.clear()
    rc = cli._windows_registry_install("uninstall")
    assert rc == 0

    deleted = set(fake_registry.deleted)
    for base in cli.BASE_KEYS:
        for name, _label, _cmd in cli.SUB_COMMANDS:
            assert f"{base}\\Shell\\{name}\\command" in deleted, (
                f"卸载没删新结构 {base}\\Shell\\{name}\\command"
            )
            # 历史遗留: v0.7.20 的 open\command / v0.7.9 的 command
            assert f"{base}\\shell\\{name}\\open\\command" in deleted
            assert f"{base}\\shell\\{name}\\command" in deleted
