# 右键菜单集成（OS Context Menu）

Pandaone AI Agent 在 **Windows / macOS / Linux** 三大平台上都提供原生右键菜单集成。右键点击文件或文件夹 → 「Pandaone」→ 选择 init / lock / unlock / status，**不用打开终端**。

## 一键启用

```bash
# 任意平台，自动检测 OS
pandaone install-context

# 强制重新安装（仅 Windows）
pandaone install-context --force

# 卸载
pandaone uninstall-context
```

## 各平台细节

### Windows（HKCU 注册表级联菜单）

- **无需管理员**（HKCU 用户级）
- **3 个位置**：任意文件 / 文件夹 / 空白处
- **4 个动作**：Init / Lock / Unlock / Status（级联子菜单）
- **图标**：使用 `pandaone.exe` 自带图标
- **幂等**：重复运行安全

手动运行：

```powershell
# 脚本随包分发，路径随安装方式不同，用 Python 定位最稳妥：
$p = python -c "import pandaone,os;print(os.path.join(os.path.dirname(pandaone.__file__),'installer','windows','install_context_menu.ps1'))"
powershell -ExecutionPolicy Bypass -File $p [-Force] [-DryRun]
```

脚本的实际位置：

| 安装方式 | 路径 |
|---|---|
| pip (`pip install pandaone-guard`) | `<Python>\Lib\site-packages\pandaone\installer\windows\` |
| Windows 安装包 (.exe) | `%LOCALAPPDATA%\Pandaone\_internal\pandaone\installer\windows\` |
| 源码仓库 | `src\pandaone\installer\windows\` |

> 注：直接写 `installer\windows\install_context_menu.ps1` **在以上三种情况下都不存在** ——
> 仓库根的 `installer\` 是 Inno Setup 的构建产物目录，不含这些脚本。

DryRun 仅打印计划不写注册表（用于测试）。

> ⚠️ Windows PowerShell 5.1 用户请注意：脚本含中文，必须带 UTF-8 BOM 才能被 5.1 正确解析
> （v0.7.34.2 起已随包分发带 BOM）。若你的脚本是旧版本自行拷贝的，请重新下载。

### macOS（Automator Quick Action）

- **服务菜单**：Finder 右键 → 「服务」→ 「Pandaone」
- **首次启用**：系统设置 → 键盘 → 快捷键 → 服务 → 勾选「文件和文件夹 → Pandaone」
- **操作菜单**：弹窗选择 init / lock / unlock / status → Terminal.app 自动打开并执行

手动运行：

```bash
bash "$(python3 -c "import pandaone,os;print(os.path.join(os.path.dirname(pandaone.__file__),'installer','macos','install_context_menu.sh'))")"
```

### Linux（Nautilus + Dolphin）

- **Nautilus（GNOME / Files）**：右键 → 「脚本」→ Pandaone
- **Dolphin（KDE）**：右键 → Actions → Pandaone → Init/Lock/Unlock/Status
- **自动检测桌面环境**（`$XDG_CURRENT_DESKTOP`）
- **用户级**：`~/.local/share/nautilus/scripts/` 和 `~/.local/share/kservices5/ServiceMenus/`

手动运行：

```bash
bash "$(python3 -c "import pandaone,os;print(os.path.join(os.path.dirname(pandaone.__file__),'installer','linux','install_context_menu.sh'))")"
```

## 工作流示例

1. 拿到一个新项目
2. **右键项目文件夹** → Pandaone → **init** → 初始化完成
3. **右键项目文件夹** → Pandaone → **lock** → 所有文件锁住
4. AI 修改文件 → 通过 `pandaone write --file X.py --reason ...` 审计
5. **右键项目文件夹** → Pandaone → **status** → 查看审计状态

## 文件清单

脚本随 `pandaone` 包分发，位于包目录的 `installer/` 子目录下：

```
<pandaone 包目录>/installer/
├── windows/
│   ├── install_context_menu.ps1       # PowerShell 安装（HKCU）
│   └── uninstall_context_menu.ps1     # PowerShell 卸载
├── macos/
│   ├── install_context_menu.sh        # bash 安装
│   ├── uninstall_context_menu.sh      # bash 卸载
│   └── Pandaone Lock.workflow/          # Automator Quick Action
│       └── Contents/
│           ├── Info.plist
│           └── document.wflow
└── linux/
    ├── install_context_menu.sh        # bash 安装（自动检测）
    ├── uninstall_context_menu.sh      # bash 卸载
    ├── nautilus/Pandaone                # Nautilus 脚本
    └── dolphin/pandaone-lock.desktop    # KDE 服务菜单
```

包目录的位置：pip 安装为 `<Python>\Lib\site-packages\pandaone\`，源码仓库为 `src\pandaone\`。
可用 `python -c "import pandaone,os;print(os.path.dirname(pandaone.__file__))"` 直接打印。

## 第一性原理

右键菜单让 Pandaone 的核心机制（**所有改动必须经过审计**）变得**不可绕过**：

- 文件被 OS 锁住（`attrib +r` / `chmod 444`）
- AI Agent 想要修改，必须先 `pandaone unlock` 或 `pandaone write`
- 而 `pandaone write` 强制 `reason / problem / approach` 三段必填
- 这强制 AI "想清楚再写"，不是"写完再编理由"

右键菜单不是便利功能，是**审计系统的最后一米**。