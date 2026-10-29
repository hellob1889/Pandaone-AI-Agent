# ============================================================
# Pandaone 右键菜单注册表结构断言测试（TDD - Red phase）
# ============================================================
# 用法（在 PowerShell 5.1 管理员）：
#   1) 先跑 install_context_menu.ps1 -DryRun 或真的安装
#   2) 再跑这个 test 脚本
#   3) 任何断言失败都退出码 1 + 输出失败原因
#
# 测试范围：
#   - 3 个入口（任意文件 / 目录 / 目录空白处）结构一致
#   - 父菜单 (Default) 为空（ExtendedSubCommandsKey 模式强制）
#   - ExtendedSubCommandsKey 值 = 相对路径 Pandaone\Shell
#   - 命令仓库 Shell\ 下 4 个 verb 完整、command 引用 pandaone.exe
#   - Init 子项带 CommandFlags = 0x20（视觉分隔）
# ============================================================

$ErrorActionPreference = 'Stop'

$TestRootKeys = @(
    '*\shell',
    'Directory\shell',
    'Directory\Background\shell'
)

$ExpectedVerbs = @('Init', 'Lock', 'Status', 'Unlock')

$failures = @()

function Assert-True {
    param([bool]$Cond, [string]$Msg)
    if (-not $Cond) {
        $script:failures += $Msg
        Write-Host "[FAIL] $Msg" -ForegroundColor Red
    } else {
        Write-Host "[OK]   $Msg" -ForegroundColor Green
    }
}

# --- 注册表读取辅助 ---
# 用 .NET Registry API 而不是 HKCU: provider：
#   - provider 把 `*` 当通配符，HKCU:\Software\Classes\*\shell\Pandaone 读不到
#   - .NET API 把 `*` 当字面 key name，100% 可靠（与 install_context_menu.ps1 同源）
function Get-RegSubKey {
    param([string]$Path)
    if ($Path -notmatch '^HKCU:\\(.+)$') { return $null }
    $subPath = $Matches[1]
    $key = $null
    try {
        $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($subPath, $false)
    } catch {}
    return $key
}

function Test-RegKey {
    param([string]$Path)
    $key = Get-RegSubKey $Path
    if (-not $key) { return $false }
    $key.Close()
    return $true
}

function Get-RegValue {
    param([string]$Path, [string]$Name)
    $key = Get-RegSubKey $Path
    if (-not $key) { return $null }
    try {
        return $key.GetValue($Name, $null)
    } catch {
        return $null
    } finally {
        $key.Close()
    }
}

# ============================================================
# 主流程：逐个入口断言结构
# ============================================================
foreach ($rootKey in $TestRootKeys) {
    Write-Host ""
    Write-Host "=== $rootKey ===" -ForegroundColor Cyan

    $baseKey = "HKCU:\Software\Classes\$rootKey\Pandaone"
    $repoKey = "$baseKey\Shell"

    # 1) 父键存在
    if (-not (Test-RegKey $baseKey)) {
        Assert-True $false "$baseKey 不存在（请先运行 install_context_menu.ps1 安装）"
        continue
    }
    Assert-True $true "$baseKey 存在"

    # 2) 父菜单 (Default) 为空（ExtendedSubCommandsKey 模式强制）
    $defaultVal = [string](Get-RegValue $baseKey '')
    $okDefault = [string]::IsNullOrEmpty($defaultVal)
    Assert-True $okDefault "$baseKey 的 (Default) 应为空字符串，实际='$defaultVal'"

    # 3) ExtendedSubCommandsKey 值 = 相对路径 Pandaone\Shell
    $esk = [string](Get-RegValue $baseKey 'ExtendedSubCommandsKey')
    $okEsk = ($esk -eq 'Pandaone\Shell')
    Assert-True $okEsk "$baseKey 的 ExtendedSubCommandsKey 应为 'Pandaone\Shell'，实际='$esk'"

    # 4) 命令仓库 Shell\ 下 4 个 verb 完整、command 引用 pandaone.exe
    foreach ($verb in $ExpectedVerbs) {
        $verbKey = "$repoKey\$verb"
        Assert-True (Test-RegKey $verbKey) "$verbKey 存在"

        $cmdKey = "$verbKey\command"
        if (-not (Test-RegKey $cmdKey)) {
            Assert-True $false "$cmdKey 存在"
            continue
        }
        $cmd = [string](Get-RegValue $cmdKey '')
        $okCmd = ((-not [string]::IsNullOrEmpty($cmd)) -and ($cmd -like '*pandaone*'))
        Assert-True $okCmd "$cmdKey 的命令引用 pandaone，实际='$cmd'"
    }

    # 5) Init 子项带 CommandFlags = 0x20（视觉分隔）
    $initKey = "$repoKey\Init"
    $flags = Get-RegValue $initKey 'CommandFlags'
    $okFlags = ($flags -eq 0x20)
    Assert-True $okFlags "$initKey 的 CommandFlags 应为 0x20，实际='$flags'"
}

Write-Host ""
if ($failures.Count -gt 0) {
    Write-Host "[FAIL] $($failures.Count) 项断言失败：" -ForegroundColor Red
    foreach ($f in $failures) {
        Write-Host "  - $f" -ForegroundColor Red
    }
    exit 1
}
Write-Host "[OK] 全部断言通过（$($TestRootKeys.Count) 个入口 x $($ExpectedVerbs.Count) 个 verb）" -ForegroundColor Green
exit 0
