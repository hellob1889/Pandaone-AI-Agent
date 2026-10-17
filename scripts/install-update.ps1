# ============================================================
# Pandaone v0.7.20 一键升级脚本
# ============================================================
# 适用: 已装 pandaone-guard < 0.7.20 的用户
# 作用: 自动卸老版 → 下载 0.7.20 wheel → 装 → update-fingerprint → 验
# 用法: irm https://raw.githubusercontent.com/hellob1889/Pandaone-AI-Agent/v0.7.20/scripts/install-update.ps1 | iex
# date: 2026-10-17
# ============================================================

$ErrorActionPreference = Stop
$TARGET_VERSION = 0.7.20
$GITHUB_REPO = hellob1889/Pandaone-AI-Agent

# --- Banner ---
Write-Host "
Write-Host =============================================== -ForegroundColor Cyan
Write-Host 