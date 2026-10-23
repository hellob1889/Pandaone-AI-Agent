# 开发指南 / Development Guide

面向在 Pandaone 仓库里改代码的人。踩过的坑写在这里，避免重复踩。

---

## 1. pytest 三连坑（最容易复发、也最难查）

这三个坑的共同特征：**测试全绿 / 全红，但和被测代码的实际行为对不上**。
几乎每次都会有人怀疑"是不是代码写错了"，其实是测试环境本身有问题。

### 坑 1：`sys.path` 注入顺序 —— 跑的是 site-packages 里的陈旧副本

**症状**：改完源码，`pytest` 却报"还是老行为"；或者你明明修好了，测试还是红。

**原因**：`tests/conftest.py` 里的 `sys.path.insert(0, ...)` 如果写在文件**中段**，
而文件顶部已经有 `import pandaone`（或某个间接 import 链触发了它），
那么 `pandaone` 会被从 **site-packages** 加载 —— 那里装的是上一次 `pip install` 的版本。

**铁律**：

```python
# tests/conftest.py —— 注入必须在这行之前
import os
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(_SRC))
os.environ["PYTHONPATH"] = str(_SRC)   # 给 subprocess 用

import pandaone  # noqa: E402  ← 必须在注入之后
```

**自检**：`python -c "import pandaone; print(pandaone.__file__)"`，
路径必须指向仓库的 `src/pandaone/`，不是 site-packages。

### 坑 2：模块顶层 `del sys.modules['pandaone*']` —— 模块对象分裂，mock 静默失效

**症状**：`mock.patch("pandaone.git_installer._can_run_git")` 打了补丁，
但被测代码还是去真的执行了外部命令；或者 `patch.object(part_002, "FP_PATH")` 改不动。

**原因**：测试模块顶层写 `del sys.modules["pandaone"]`（有时带通配符），
下一次 `import pandaone` 会**新建一个模块对象**。
测试里 patch 的是新对象，被测代码持有的却可能是旧对象（或者反过来）——
补丁打在了没人用的那个对象上，**不报错，只是没效果**。

**铁律**：用 `importlib.reload`，不要 `del sys.modules`。

```python
import importlib
from pandaone.cli_chunks import part_002

importlib.reload(part_002)   # ✅ 重置模块状态，模块对象保持同一性
# del sys.modules["pandaone.cli_chunks.part_002"]   # ❌ 制造分裂
```

**排查信号**：mock 明明 patch 了却"没生效"，且没有任何报错 —— 先怀疑模块分裂。

### 坑 3：subprocess 跑被测包 —— 跑到陈旧副本

**症状**：pytest 里断言通过，手工跑命令却行为不同。

**原因**：`subprocess.run([sys.executable, "-m", "pandaone", ...])` 起的是**新进程**，
新进程**不继承** pytest 进程里的 `sys.path` 注入 —— 它按自己的规则找 `pandaone`，
于是又落到 site-packages。

**铁律**：subprocess 显式传环境变量。

```python
env = os.environ.copy()
env["PYTHONPATH"] = str(_SRC)          # ← 必须
subprocess.run([sys.executable, "-m", "pandaone", ...], env=env)
```

`conftest.py` 里设 `os.environ["PYTHONPATH"]` 只解决"继承了环境变量的子进程"，
**不解决**显式传 `env=` 的调用点 —— 那里的 `env` 会覆盖继承值。

### 附带一条：Windows 控制台工具输出不是 UTF-8

`taskkill` / `netstat` / `wmic` 在中文 Windows 上输出 **GBK**。
`subprocess.run(..., text=True)` 会按 locale 解码，遇到非法字节直接
`UnicodeDecodeError` 把调用方炸掉。

```python
subprocess.run(cmd, capture_output=True, text=True,
               encoding="utf-8", errors="replace")   # ← 两个都要
```

---

## 2. 指纹（L5 自校验）与开发期

L5 承诺：**agent 改了 pandaone 本体来跳过审计，必须能检测到**。

指纹按 `{version, hash, form}` 绑定：

- `version` 不同 → 合法升级，自动刷新指纹
- `form` 不同（`source` ↔ `frozen`，即源码版 ↔ .exe 版）→ 合法部署切换，自动刷新
- `version` 相同 + `form` 相同 + `hash` 不同 → **判篡改**，整个 CLI 锁死

因此：**改完源码必须抬 `pyproject.toml` 的版本号**，否则整片测试会红
（那是指纹锁死，不是代码坏了）。

合法的快速通道：

```bash
python -m pandaone --update-fingerprint 0000     # 该路径豁免指纹校验
```

> ⚠️ 不要为了"让测试变绿"给源码树开指纹豁免 —— 那等于拆掉 L5 的承诺。

---

## 3. i18n 门禁

面向用户的文案必须走 `pandaone.i18n.t(key, **kw)`，**禁止硬编码中文**。
内部异常/技术描述用英文。

```bash
python scripts/audit_i18n.py     # 检查硬编码 + 覆盖率
```

新增 key 必须**中英各一份、同名同参**。当前覆盖率 401/401 = 100%。

---

## 4. 子命令注册：不要往 `cli_chunks` 里塞大段代码

`src/pandaone/cli.py` 只有 42 行，它遍历 `cli_chunks/part_*.py` 逐块 `exec()` 进自己的 globals。
单个 chunk 逼近 **24KB** 时会撞上 MCP 单次推送上限。

**新增子命令走"独立模块 + `src/pandaone/__main__.py` monkey-patch"**：

```python
# src/pandaone/cmd_xxx.py
def add_xxx_parser(sub): ...
def cmd_xxx(args): ...

# src/pandaone/__main__.py
cli.COMMANDS["xxx"] = cmd_xxx
# 并在 _patched_build_parser 里 add_xxx_parser(sub_action)
```

`doctor` 就是这么做的（见 `cmd_doctor.py`）。

---

## 5. 打包（Windows .exe）

```bash
python -m venv work/_buildenv
work/_buildenv/Scripts/pip install pyinstaller watchdog openpyxl python-docx reportlab pyyaml psutil setuptools
work/_buildenv/Scripts/python build_pyinstaller.py
```

产物：`dist/pandaone/`（三个 exe）+ `installer/Output/PandaoneSetup-<版本>-x64.exe`。

### 打包链路的三个硬约束

1. **`cli.py` 用 `exec()` 加载 `cli_chunks/`** —— PyInstaller 的静态分析抓不到 chunk 里的 import。
   所有第三方依赖（`psutil`、`yaml`、`watchdog`…）和 chunk 里 import 的
   `pandaone.*` 模块都必须在 `HIDDEN_IMPORTS` 里显式声明。

2. **包目录要作为「数据」整棵复制进包** —— 否则 `.py` 源码进了 PYZ 就从磁盘上消失，
   `exec()` 加载器读不到、指纹也覆盖不到。

3. **frozen 下 `importlib.util.find_spec()` 拿不到包目录** —— 指纹根目录要走
   `sys._MEIPASS/<pkg>` 分支；版本号读 `_MEIPASS/pandaone/_build_info.py`
   （由 `build_pyinstaller.py` 注入）。

### 环境注意

- 官方 Inno Setup **不带简体中文 `.isl`** —— 打包脚本会自动探测，缺失就退回英文向导。
- Inno Setup 6 不认 `AppURL`（要用 `AppPublisherURL`）。
- 本机全局 Python 里有 `typing` 3.7.4.3 backport 时 PyInstaller 会拒绝启动 ——
  **不要卸载全局环境里的包**，用独立 venv 打包。
- `git clone <本地路径>` 在 Windows 上会因为 `git-upload-pack` 不在 PATH 而失败；
  **`git bundle` 才是跨平台零依赖的可靠备份载体**。

---

## 6. 测试

```bash
python -m pytest tests/ -q --timeout=180 -p no:cacheprovider
```

基线（v0.7.24.0）：`494 passed, 9 skipped`（约 171 秒）。

`--collect-only` 不会污染环境；改了源码又没抬版本号时，测试会**整片红** ——
先确认是不是指纹锁死，而不是急着改代码。
