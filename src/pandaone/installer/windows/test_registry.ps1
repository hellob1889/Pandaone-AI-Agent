# ============================================================
# Pandaone 右键菜单注册表结构断言测试（TDD - Red phase）
# ============================================================
# 用法（在 PowerShell 5.1）：
#   1) 先用其中任一入口安装：
#        powershell -ExecutionPolicy Bypass -File installer\windows\install_context_menu.ps1 -Force
#        pandaone install-context
#   2) 再跑这个 test 脚本
#   3) 任何断言失败都退出码 1 + 输出失败原因
#
# 测试范围（两条安装路径必须产出同一份注册表结构）：
#   权威结构 = CLI src/pandaone/cli_chunks/part_006.py
#            = Inno Setup src/pandaone/installer/codeaudit.iss
#   - 3 个入口（任意文件 / 目录 / 目录空白处）结构一致
#   - 父菜单 MUIVerb 提供显示名
#   - 父菜单 (Default) 为空或未设置（MS 文档要求级联菜单父键默认值显示为
#     "(value not set)"，即值不存在；写空串是另一种状态）
#   - 父菜单不含 SubCommands（写它会让 Explorer 静默隐藏整个级联菜单）
#   - ExtendedSubCommandsKey 值 = 相对路径 Pandaone\Shell
#   - 命令仓库 Shell\ 下 4 个 verb 完整、command 引用 pandaone.exe
#   - command 不含 --trust-default（v0.7.20 P0-3：会静默重写指纹基线）
#   - verb 子项不含 CommandFlags（EXPCMDFLAGS，0x20 = ECF_SEPARATORBEFORE，
#     仅对顶层菜单项生效；本菜单 verb 在级联子菜单内，加了也不生效）
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

function Test-RegHasValue {
    # 判断某个值是否"存在"（区别于"存在但为空"）。
    # 值的名字列表里没有它 = 未设置；名字在列表里但数据为空 = 设置了空串。
    param([string]$Path, [string]$Name)
    $key = Get-RegSubKey $Path
    if (-not $key) { return $false }
    try {
        foreach ($n in $key.GetValueNames()) {
            if ($n -eq $Name) { return $true }
        }
        return $false
    } catch {
        return $false
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
        Assert-True $false "$baseKey 不存在（请先运行 install_context_menu.ps1 或 pandaone install-context 安装）"
        continue
    }
    Assert-True $true "$baseKey 存在"

    # 2) 父菜单 (Default) 为空或未设置（ExtendedSubCommandsKey 模式强制）
    #    CLI 不写 (Default)，MS 文档要求级联菜单父键默认值显示为 "(value not set)"；
    #    写空串是另一种状态，所以这里同时接受"未设置"和"空串"两种等价写法。
    $defaultVal = [string](Get-RegValue $baseKey '')
    $okDefault = [string]::IsNullOrEmpty($defaultVal)
    Assert-True $okDefault "$baseKey 的 (Default) 应为空或未设置，实际='$defaultVal'"

    # 3) 父菜单 MUIVerb 提供显示名（CLI / Inno Setup 都写；缺了右键菜单是空标题）
    $muiv = [string](Get-RegValue $baseKey 'MUIVerb')
    $okMuiv = (Test-RegHasValue $baseKey 'MUIVerb') -and (-not [string]::IsNullOrEmpty($muiv))
    Assert-True $okMuiv "$baseKey 的 MUIVerb 应存在且非空，实际='$muiv'"

    # 4) ExtendedSubCommandsKey 值 = 相对路径 Pandaone\Shell
    $esk = [string](Get-RegValue $baseKey 'ExtendedSubCommandsKey')
    $okEsk = ($esk -eq 'Pandaone\Shell')
    Assert-True $okEsk "$baseKey 的 ExtendedSubCommandsKey 应为 'Pandaone\Shell'，实际='$esk'"

    # 5) 父菜单不得有 SubCommands（空串或列表都会让 Explorer 隐藏整个级联菜单）
    $hasSub = Test-RegHasValue $baseKey 'SubCommands'
    Assert-True (-not $hasSub) "$baseKey 不应写 SubCommands（Explorer 会判 0 子菜单并隐藏整个菜单）"

    # 6) 命令仓库 Shell\ 下 4 个 verb 完整、command 引用 pandaone.exe
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

        # 7) command 不得带 --trust-default（v0.7.20 P0-3）
        $okNoTrust = ($cmd -notlike '*--trust-default*')
        Assert-True $okNoTrust "$cmdKey 的命令不应带 --trust-default（会静默重写指纹基线），实际='$cmd'"
    }

    # 8) verb 子项不应有 CommandFlags（0x20 = ECF_SEPARATORBEFORE，仅顶层菜单项生效）
    $initKey = "$repoKey\Init"
    $hasFlags = Test-RegHasValue $initKey 'CommandFlags'
    Assert-True (-not $hasFlags) "$initKey 不应有 CommandFlags（0x20 = ECF_SEPARATORBEFORE，对级联子菜单内的 verb 不生效）"
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
