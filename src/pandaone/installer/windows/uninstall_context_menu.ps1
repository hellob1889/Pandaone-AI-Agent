# ============================================================
# Pandaone AI Agent Windows 右键菜单卸载脚本
# ============================================================
# 用法：
#   powershell -ExecutionPolicy Bypass -File installer\windows\uninstall_context_menu.ps1
#
# 第一性原理：
#   - 只删除 Pandaone 命名前缀的注册表项，不影响其他右键菜单
#   - 完全幂等：重复运行安全
#   - 无需管理员权限（HKCU 是用户级）
# ============================================================

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

# Phase 10: 检测用户语言偏好
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

# Phase 10: 双语提示
$TXT_TITLE = if ($USER_LANG -eq 'en') { 'Pandaone Windows Context Menu Uninstaller' } else { 'Pandaone Windows 右键菜单卸载程序' }
$TXT_SKIP = if ($USER_LANG -eq 'en') { '[SKIP]   {0} (not exists)' } else { '[SKIP]   {0} (不存在)' }
$TXT_NOT_INSTALLED = if ($USER_LANG -eq 'en') { '[INFO] Pandaone context menu not installed.' } else { '[INFO] Pandaone 右键菜单未安装。' }
$TXT_REMOVED = if ($USER_LANG -eq 'en') { '[OK] Removed {0} registry entries.' } else { '[OK] 已移除 {0} 处注册表项。' }
$TXT_RESTART = if ($USER_LANG -eq 'en') { 'If menu still appears, restart Explorer:' } else { '如果右键菜单依然残留，请重启资源管理器：' }
$TXT_RESTART_CMD = if ($USER_LANG -eq 'en') { '  taskkill /f /im explorer.exe && start explorer.exe' } else { '  taskkill /f /im explorer.exe && start explorer.exe' }

Write-Host "==============================================="
Write-Host $TXT_TITLE
Write-Host "==============================================="
Write-Host ""

$keysToRemove = @(
    "HKCU:\Software\Classes\*\shell\Pandaone",
    "HKCU:\Software\Classes\Directory\shell\Pandaone",
    "HKCU:\Software\Classes\Directory\Background\shell\Pandaone"
)

$removed = 0
foreach ($k in $keysToRemove) {
    # Bug #8 fix: PS5.1 native command glob `*`，reg.exe 不可靠。
    # 改用 .NET [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey()
    # — 100% 把 `*` 当字面 key name，无 glob 行为。
    if ($k -notmatch '^HKCU:\\(.+)$') {
        Write-Host ($TXT_SKIP -f $k)
        continue
    }
    $subPath = $Matches[1]
    $key = $null
    try {
        $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($subPath, $false)
    } catch {}
    if ($key) {
        $key.Close()
        Write-Host "[REMOVE] $k"
        try {
            [Microsoft.Win32.Registry]::CurrentUser.DeleteSubKeyTree($subPath, $false)
            $removed++
        } catch {}
    } else {
        Write-Host ($TXT_SKIP -f $k)
    }
}

# 也尝试清理 Inno Setup 早期版本遗留的命名（旧版用 PandaoneInit / PandaoneWatch）
$legacyKeys = @(
    "HKCU:\Software\Classes\*\shell\PandaoneInit",
    "HKCU:\Software\Classes\*\shell\PandaoneWatch",
    "HKCU:\Software\Classes\Directory\shell\PandaoneInit"
)
foreach ($k in $legacyKeys) {
    # Bug #8 fix: 同上 .NET API
    if ($k -notmatch '^HKCU:\\(.+)$') { continue }
    $subPath = $Matches[1]
    $key = $null
    try {
        $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($subPath, $false)
    } catch {}
    if ($key) {
        $key.Close()
        Write-Host "[REMOVE-LEGACY] $k"
        try {
            [Microsoft.Win32.Registry]::CurrentUser.DeleteSubKeyTree($subPath, $false)
            $removed++
        } catch {}
    }
}

Write-Host ""
if ($removed -eq 0) {
    Write-Host $TXT_NOT_INSTALLED
} else {
    Write-Host ($TXT_REMOVED -f $removed)
}

Write-Host ""
Write-Host $TXT_RESTART
Write-Host $TXT_RESTART_CMD
Write-Host ""