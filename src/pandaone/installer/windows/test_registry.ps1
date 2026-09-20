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
        Write-Host 