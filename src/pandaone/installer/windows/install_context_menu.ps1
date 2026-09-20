# ============================================================
# Pandaone AI Agent Windows 右键菜单安装脚本
# ============================================================
# 用法（管理员或普通用户均可）：
#   powershell -ExecutionPolicy Bypass -File installer\windows\install_context_menu.ps1
#
# 第一性原理：
#   - 用 HKCU (HKEY_CURRENT_USER) 而非 HKLM，无需管理员权限
#   - 级联菜单（submenu）结构：右键 → "Pandaone" → 4 个子动作
#   - 每个动作都调用 pandaone.exe（必须在 PATH，或通过 PYTHON_SCRIPTS 自动定位）
#   - 幂等：重复运行安全（先检测再写入）
#
# 对抗式审查：
#   - 攻击：恶意软件假冒 install 脚本篡改注册表
#     缓解：只写入 *Pandaone* 命名前缀，不影响其他菜单项
#   - 攻击：pandaone.exe 路径被替换
#     缓解：用绝对路径 + fallback 搜索
#   - 攻击：用户已有同名菜单项冲突
#     缓解：用 MUIVerb + subCommands 注册到独立命名空间
#
# 注册表结构：
#   HKCU\Software\Classes\*\shell\Pandaone            (任意文件)
#       \shell\Init\shell\open\command              (pandaone init)
#       \shell\Lock\shell\open\command              (pandaone lock)
#       \shell\Status\shell\open\command            (pandaone status)
#       \shell\Write\shell\open\command             (pandaone write --file)
#   HKCU\Software\Classes\Directory\shell\Pandaone    (目录)
#   HKCU\Software\Classes\Directory\Background\shell\Pandaone  (空白处)
# ============================================================

[CmdletBinding()]
param(
    [switch]$Force,      # 强制重新安装（即使已安装）
    [switch]$DryRun      # 只打印计划，不实际写注册表（用于测试）
)

$ErrorActionPreference = 'Stop'
if ($DryRun) {
    $script:DryRun = $true
    Write-Host "[INFO] DryRun 模式 — 仅打印计划，不修改注册表"
    Write-Host ""
}

# ============================================================
# 1. 定位 pandaone 可执行文件
# ============================================================
function Find-PandaoneExe {
    <#
    搜索顺序：
      1. PATH 中的 pandaone.exe / pandaone
      2. Python 用户脚本目录（python -m site --user-base）
      3. 常见安装路径（Program Files、autopf）
      4. 退而求其次：python -m pandaone（依赖 python 在 PATH）
    #>
    $exeName = if ($IsWindows -or $env:OS -match 'Windows') { 'pandaone.exe' } else { 'pandaone' }

    # 1) 直接在 PATH
    $cmd = Get-Command pandaone -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { return $cmd.Source }

    # 2) Python 用户脚本
    try {
        $py = Get-Command python -ErrorAction SilentlyContinue
        if ($py) {
            $siteOut = & python -m site --user-site 2>$null
            if ($siteOut) {
                $scriptsRoot = Split-Path $siteOut -Parent
                $candidates = @(
                    (Join-Path $scriptsRoot 'Scripts\pandaone.exe'),
                    (Join-Path $scriptsRoot 'bin\pandaone')
                )
                foreach ($c in $candidates) {
                    if (Test-Path $c) { return (Resolve-Path $c).Path }
                }
            }
        }
    } catch {}

    # 3) 常见安装路径
    $candidates = @(
        "$env:ProgramFiles\Pandaone\pandaone.exe",
        "${env:ProgramFiles(x86)}\Pandaone\pandaone.exe",
        "$env:LOCALAPPDATA\Programs\Pandaone\pandaone.exe",
        "$env:LOCALAPPDATA\Pandaone\pandaone.exe",
        "$env:USERPROFILE\.local\bin\pandaone.exe"
    )
    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c)) { return (Resolve-Path $c).Path }
    }

    # 4) 最终 fallback：返回 Python 调用形式（pandaone 注册成 Python -m 模块也行）
    return $null
}

# ============================================================
# 2. 注册表写入辅助
# ============================================================
function Set-RegValue {
    param([string]$Path, [string]$Name, [string]$Type, [string]$Value)
    # 名称为空 → 注册表"默认"值（regedit 显示为 "(Default)"）
    $regName = if ($Name -eq '') { '(Default)' } else { $Name }
    if ($script:DryRun) {
        Write-Host "  [DRY] Set $Path :: $regName = $Value ($Type)"
        return
    }
    # Bug #8 fix: PS5.1 registry provider 的 New-Item/New-ItemProperty
    # 不支持 -LiteralPath（Test-Path/Remove-Item 支持），导致
    # `HKCU:\Software\Classes\*\shell\Pandaone` 中 `*` 被当通配符 → 永久阻塞。
    # 改用 .NET [Microsoft.Win32.Registry] API：原生把 `*` 当字面 key name。
    # reg.exe / cmd.exe 包装也曾尝试，但 PS5.1 native command 仍会 glob，
    # 报 "Invalid key name"，不可靠。
    if ($Path -notmatch '^HKCU:\\(.+)$') {
        throw "Set-RegValue only supports HKCU:\ paths (got $Path)"
    }
    $subPath = $Matches[1]
    $kind = switch ($Type) {
        'String'       { [Microsoft.Win32.RegistryValueKind]::String }
        'ExpandString' { [Microsoft.Win32.RegistryValueKind]::ExpandString }
        'DWord'        { [Microsoft.Win32.RegistryValueKind]::DWord }
        'Binary'       { [Microsoft.Win32.RegistryValueKind]::Binary }
        default        { [Microsoft.Win32.RegistryValueKind]::String }
    }
    # CreateSubKey 自动创建父 key（即使中间层级不存在）
    $key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey($subPath)
    # PS5.1 SetValue 对 DWord/Binary 需要显式 int[]/byte[] 强转（0x20 默认推断为 long 触发 ArgumentException）
    if ($kind -eq [Microsoft.Win32.RegistryValueKind]::DWord) {
        $typedValue = [int]$Value
    } elseif ($kind -eq [Microsoft.Win32.RegistryValueKind]::Binary) {
        $typedValue = [byte[]]$Value
    } else {
        $typedValue = [string]$Value
    }
    if ($Name -eq '') {
        $key.SetValue($null, $typedValue, $kind)   # null = "(Default)"
    } else {
        $key.SetValue($Name, $typedValue, $kind)
    }
    $key.Close()
}

function Remove-RegTree {
    param([string]$Path)
    if ($script:DryRun) {
        Write-Host "  [DRY] Remove $Path"
        return
    }
    # Bug #8 fix: 改用 .NET DeleteSubKeyTree，避开 PS provider 通配符 glob
    if ($Path -notmatch '^HKCU:\\(.+)$') {
        throw "Remove-RegTree only supports HKCU:\ paths (got $Path)"
    }
    $subPath = $Matches[1]
    try {
        # throwOnMissingSubKey=$false 让"key 不存在"静默通过（幂等清理）
        [Microsoft.Win32.Registry]::CurrentUser.DeleteSubKeyTree($subPath, $false)
    } catch {
        # .NET 在 key 不存在时抛 IOException；按幂等要求忽略
        if ($_.Exception.GetType().Name -ne 'IOException') {
            Write-Warning "DeleteSubKeyTree failed for $Path : $_"
        }
    }
}

# ============================================================
# 3. 构建级联菜单
# ============================================================
function Install-CascadeMenu {
    param(
        [string]$RootKey,      # e.g. "Directory\shell"
        [string]$PandaonePath
    )

    $baseKey = "HKCU:\Software\Classes\$RootKey\Pandaone"

    # 主菜单（cascade = submenu，V2 ExtendedSubCommandsKey 模式）
    Set-RegValue -Path $baseKey -Name '' -Type 'String' -Value ''
    Set-RegValue -Path $baseKey -Name 'Icon' -Type 'String' -Value "`"$PandaonePath`",0"
    Set-RegValue -Path $baseKey -Name 'ExtendedSubCommandsKey' -Type 'String' -Value 'Pandaone\Shell'

    $repo = "$baseKey\Shell"

    # 1) Init
    $initKey = "$repo\Init"
    Set-RegValue -Path $initKey -Name '' -Type 'String' -Value '初始化 Pandaone (init)'
    Set-RegValue -Path $initKey -Name 'Icon' -Type 'String' -Value "`"$PandaonePath`",0"
    Set-RegValue -Path $initKey -Name 'CommandFlags' -Type 'DWord' -Value 0x20
    Set-RegValue -Path "$initKey\command" -Name '' -Type 'String' -Value "`"$PandaonePath`" --silent --trust-default init --root `"%V`""

    # 2) Lock
    $lockKey = "$baseKey\shell\Lock"
    Set-RegValue -Path $lockKey -Name '' -Type 'String' -Value '锁定文件 (lock)'
    Set-RegValue -Path $lockKey -Name 'Icon' -Type 'String' -Value "`"$PandaonePath`",0"
    Set-RegValue -Path "$lockKey\command" -Name '' -Type 'String' -Value "`"$PandaonePath`" --silent --trust-default lock --root `"%V`""

    # 3) Status
    $statusKey = "$baseKey\shell\Status"
    Set-RegValue -Path $statusKey -Name '' -Type 'String' -Value '查看状态 (status)'
    Set-RegValue -Path $statusKey -Name 'Icon' -Type 'String' -Value "`"$PandaonePath`",0"
    Set-RegValue -Path "$statusKey\command" -Name '' -Type 'String' -Value "`"$PandaonePath`" --silent --trust-default status --root `"%V`""

    # 4) Unlock
    $unlockKey = "$baseKey\shell\Unlock"
    Set-RegValue -Path $unlockKey -Name '' -Type 'String' -Value '解锁文件 (unlock)'
    Set-RegValue -Path $unlockKey -Name 'Icon' -Type 'String' -Value "`"$PandaonePath`",0"
    Set-RegValue -Path "$unlockKey\command" -Name '' -Type 'String' -Value "`"$PandaonePath`" --silent --trust-default unlock --root `"%V`""
}

# ============================================================
# 4. 主流程
# ============================================================

# Phase 10: 检测用户语言偏好（~/.pandaone/config.json → 否则 zh-CN）
$USER_LANG = 'zh-CN'
try {
    $configJson = "$env:USERPROFILE\.pandaone\config.json"
    if (Test-Path $configJson) {
        $cfg = Get-Content $configJson -Raw | ConvertFrom-Json -ErrorAction SilentlyContinue
        if ($cfg -and $cfg.lang -eq 'en') {
            $USER_LANG = 'en'
        }
    }
} catch {}

# Phase 10: 双语提示（中文 + 英文）
$TXT_TITLE = if ($USER_LANG -eq 'en') { 'Pandaone Windows Context Menu Installer' } else { 'Pandaone Windows 右键菜单安装程序' }
$TXT_FOUND = if ($USER_LANG -eq 'en') { '[OK] pandaone found: {0}' } else { '[OK] 找到 pandaone: {0}' }
$TXT_NOT_FOUND = if ($USER_LANG -eq 'en') { '[WARN] pandaone executable not found!' } else { '[WARN] 未找到 pandaone 可执行文件！' }
$TXT_INSTALL_HINT_1 = if ($USER_LANG -eq 'en') { 'Please install Pandaone first:' } else { '请先安装 Pandaone：' }
$TXT_INSTALL_HINT_2 = if ($USER_LANG -eq 'en') { '  pip install pandaone-guard' } else { '  pip install pandaone-guard' }
$TXT_INSTALL_HINT_3 = if ($USER_LANG -eq 'en') { 'Or:' } else { '或者：' }
$TXT_INSTALL_HINT_4 = if ($USER_LANG -eq 'en') { '  pip install git+https://github.com/hellob1889/Pandaone-AI-Agent.git' } else { '  pip install git+https://github.com/hellob1889/Pandaone-AI-Agent.git' }
$TXT_CONFIRM_CONTINUE = if ($USER_LANG -eq 'en') { 'Continue anyway (menu items will use "python -m pandaone")? [y/N]' } else { '是否仍要继续安装（菜单项将使用 "python -m pandaone" 作为命令）? [y/N]' }
$TXT_CANCELLED = if ($USER_LANG -eq 'en') { 'Cancelled.' } else { '已取消。' }
$TXT_ALREADY_INSTALLED = if ($USER_LANG -eq 'en') { '[INFO] Pandaone context menu already installed. Use -Force to reinstall.' } else { '[INFO] Pandaone 右键菜单已存在。使用 -Force 重新安装。' }
$TXT_CONFIRM_REINSTALL = if ($USER_LANG -eq 'en') { 'Reinstall? [y/N]' } else { '是否重新安装？[y/N]' }
$TXT_STEP_CLEAN = if ($USER_LANG -eq 'en') { '[1/4] Cleaning old entries...' } else { '[1/4] 清理旧条目...' }
$TXT_STEP_FILES = if ($USER_LANG -eq 'en') { '[2/4] Registering file context menu...' } else { '[2/4] 注册「任意文件」右键菜单...' }
$TXT_STEP_DIRS = if ($USER_LANG -eq 'en') { '[3/4] Registering directory context menu...' } else { '[3/4] 注册「目录」右键菜单...' }
$TXT_STEP_BG = if ($USER_LANG -eq 'en') { '[4/4] Registering background context menu...' } else { '[4/4] 注册「空白处」右键菜单...' }
$TXT_DONE = if ($USER_LANG -eq 'en') { '[OK] Installation complete!' } else { '[OK] 安装完成！' }
$TXT_TEST = if ($USER_LANG -eq 'en') { 'How to test:' } else { '测试方法：' }
$TXT_TEST_1 = if ($USER_LANG -eq 'en') { '  1. Right-click in any directory' } else { '  1. 在任意目录空白处点击右键' }
$TXT_TEST_2 = if ($USER_LANG -eq 'en') { '  2. See "Pandaone" cascade menu' } else { '  2. 看到「Pandaone 审计工具」级联菜单' }
$TXT_TEST_3 = if ($USER_LANG -eq 'en') { '  3. Expand to see: Init / Lock / Unlock / Status' } else { '  3. 展开后看到：Init / Lock / Unlock / Status' }
$TXT_UNINST = if ($USER_LANG -eq 'en') { 'To uninstall:' } else { '卸载：' }
$TXT_UNINST_CMD = if ($USER_LANG -eq 'en') { '  powershell -ExecutionPolicy Bypass -File installer\windows\uninstall_context_menu.ps1' } else { '  powershell -ExecutionPolicy Bypass -File installer\windows\uninstall_context_menu.ps1' }
$TXT_RESTART = if ($USER_LANG -eq 'en') { 'If menu does not appear, restart Explorer:' } else { '如果右键菜单没立刻出现，请重启资源管理器：' }
$TXT_RESTART_CMD = if ($USER_LANG -eq 'en') { '  taskkill /f /im explorer.exe && start explorer.exe' } else { '  taskkill /f /im explorer.exe && start explorer.exe' }

Write-Host "==============================================="
Write-Host $TXT_TITLE
Write-Host "==============================================="
Write-Host ""

$pandaonePath = Find-PandaoneExe

if (-not $pandaonePath) {
    Write-Warning $TXT_NOT_FOUND
    Write-Host ""
    Write-Host $TXT_INSTALL_HINT_1
    Write-Host $TXT_INSTALL_HINT_2
    Write-Host ""
    Write-Host $TXT_INSTALL_HINT_3
    Write-Host $TXT_INSTALL_HINT_4
    Write-Host ""
    $confirm = Read-Host $TXT_CONFIRM_CONTINUE
    if ($confirm -ne 'y' -and $confirm -ne 'Y') {
        Write-Host $TXT_CANCELLED
        exit 1
    }
    $pandaonePath = 'python'
    $commandSuffix = '-m pandaone'
} else {
    Write-Host ($TXT_FOUND -f $pandaonePath)
    $commandSuffix = ''
}

# 检查是否已安装
$markerKey = "HKCU:\Software\Classes\Directory\shell\Pandaone"
if ((Test-Path $markerKey) -and -not $Force) {
    Write-Host ""
    Write-Host $TXT_ALREADY_INSTALLED
    $confirm = Read-Host $TXT_CONFIRM_REINSTALL
    if ($confirm -ne 'y' -and $confirm -ne 'Y') {
        Write-Host $TXT_CANCELLED
        exit 0
    }
}

# 先清理旧条目
Write-Host ""
Write-Host $TXT_STEP_CLEAN
Remove-RegTree "HKCU:\Software\Classes\*\shell\Pandaone"
Remove-RegTree "HKCU:\Software\Classes\Directory\shell\Pandaone"
Remove-RegTree "HKCU:\Software\Classes\Directory\Background\shell\Pandaone"

# 如果使用 python -m，要修改命令
if ($commandSuffix) {
    Set-Item -Path Env:SUFFIX -Value $commandSuffix
}

Write-Host $TXT_STEP_FILES
Install-CascadeMenu -RootKey "*\shell" -PandaonePath $pandaonePath

Write-Host $TXT_STEP_DIRS
Install-CascadeMenu -RootKey "Directory\shell" -PandaonePath $pandaonePath

Write-Host $TXT_STEP_BG
Install-CascadeMenu -RootKey "Directory\Background\shell" -PandaonePath $pandaonePath

# 刷新资源管理器
Write-Host ""
Write-Host $TXT_DONE
Write-Host ""
Write-Host $TXT_TEST
Write-Host $TXT_TEST_1
Write-Host $TXT_TEST_2
Write-Host $TXT_TEST_3
Write-Host ""
Write-Host $TXT_UNINST
Write-Host $TXT_UNINST_CMD
Write-Host ""
Write-Host $TXT_RESTART
Write-Host $TXT_RESTART_CMD
Write-Host ""