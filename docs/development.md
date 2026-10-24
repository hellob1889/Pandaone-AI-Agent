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

4. **发布必须抬版本号** —— 同版本重打包 = 存量用户集体变砖（详见第 7 节）。
   `build_pyinstaller.py` 已把它做成硬门禁：同版本直接拒绝，
   除非显式 `--allow-same-version`（仅限本地验证，不要发布）。

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

基线（v0.7.26.0）：`513 passed, 9 skipped`（约 180 秒）。

`--collect-only` 不会污染环境；改了源码又没抬版本号时，测试会**整片红** ——
先确认是不是指纹锁死，而不是急着改代码。

---

## 7. 发布链路铁律（.exe）

### 7.1 同版本重打包 = 存量用户集体变砖

frozen 形态的指纹记录是 `{version, hash, form}`（`~/.pandaone_fp.txt`）。
`check_fingerprint()` 的判定顺序：

```
hash 相同                    → 直接放行（不看版本）
hash 不同 + strict           → 判篡改，锁死
hash 不同 + 版本号变了       → 自动刷新指纹，放行
hash 不同 + 形态变了         → 自动刷新指纹，放行
hash 不同 + 版本与形态都没变 → 判篡改，锁死（rc=1）
```

exe 的字节一变，hash 就变。**版本号不变 = 走进最后一行 = 存量用户全部被锁死**
（`status` / `doctor` / `backup` 全都跑不了，只能 `--update-fingerprint 0000` 救）。

所以：**每次发布必须抬 `pyproject.toml` 的版本号**。
`build_pyinstaller.py` 把这条做成了硬门禁：记录上次成功打包的版本
（`.pandaone/release_state.json`），同版本直接 `SystemExit`；
只有显式 `--allow-same-version` 才放行（仅限本地验证，不要发布）。

实测证据（v0.7.26.0）：同版本 + 改坏 hash → `rc=1` + "指纹不匹配，可能被篡改"；
版本从 0.7.25.0 抬到 0.7.26.0 → 自动刷新 → `rc=0`。

### 7.2 验证篡改锁死必须用真命令

`pandaone --version` / `--help` 是 meta 命令，**按设计跳过指纹检查**（v0.7.19）。
拿它们验证"篡改会不会锁死"会得到假阴性（rc=0，看着像没锁）。
必须用真命令，例如 `status`：

```powershell
# 沙盒 HOME 里把指纹 hash 改坏，版本号保持与 exe 一致
pandaone.exe status   # → rc=1 + 指纹不匹配提示
```

### 7.3 frozen 形态不能假设有 pip / 有解释器

frozen 形态下 `sys.executable` **就是 `pandaone.exe` 本身**，
既没有 `pip`，也没有 `-m 模块` 的语义。
任何 `sys.executable -m xxx` 都会变成"把 xxx 当成 CLI 子命令"，
报 `argument command: invalid choice: 'xxx'`。

| 场景 | 源码形态 | frozen 形态 |
|---|---|---|
| 升级 | `[python, "-m", "pip", "install", ...]` | 无 pip → 走安装包：同目录找 `PandaoneSetup-<版本>-x64.exe` |
| 起仪表盘 | `[python, "-m", "pandaone", "serve", ...]` | `[pandaone.exe, "serve", ...]` |
| 可执行目录 | `sysconfig.get_path("scripts")` | `Path(sys.executable).parent` |

写新命令时，**只要它会 spawn 子进程，就必须同时想清楚 frozen 分支**。

### 7.4 端到端必须用真正要交付的产物

源码树跑通 ≠ 交付物可用。v0.7.26.0 的三个 bug 全部只在 `dist/pandaone/pandaone.exe`
上才暴露 —— 源码树里跑 `upgrade` 一切正常，因为 `sys.executable` 是真的 python。

标准沙盒姿势：

- 重定向 `APPDATA` / `USERPROFILE` / `HOME` —— 隔离真实 IDE 配置与指纹文件；
- 快照并还原 `HKCU\Environment\Path` —— `setup` 会写它；
- 跑完按沙盒路径清理子进程（看门狗 / 仪表盘会在后台活下来）。

### 7.5 打包完成后先验版本，再验别的

```powershell
dist\pandaone\pandaone.exe --version    # 必须是刚抬的版本号
```

如果 `--version` 显示的还是旧版本，说明 `build/_build_info.py` 没重新注入，
后面所有验证都是白做。
