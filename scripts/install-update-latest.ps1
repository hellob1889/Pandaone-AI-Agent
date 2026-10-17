# ============================================================
# Pandaone 一键升级脚本 (自动 fetch 最新 release)
# ============================================================
# 适用: 已装 pandaone-guard 的 Windows 用户
# 作用: 自动查 GitHub 最新 release → 下载 wheel → 卸老 → 装 → update-fingerprint → 验
# 用法 (PowerShell 管理员):
#   irm https://raw.githubusercontent.com/hellob1889/Pandaone-AI-Agent/main/scripts/install-update-latest.ps1 | iex
#
# 或装特定版本:
#   $env:PANDAONE_TARGET_VERSION="0.7.20"; irm ... | iex
# ============================================================

$ErrorActionPreference = "Stop"
$GITHUB_REPO = "hellob1889/Pandaone-AI-Agent"
$TARGET_VERSION = $env:PANDAONE_TARGET_VERSION  # 可选, 默认取最新

# --- 1. 查最新 version ---
if (-not $TARGET_VERSION) {
    Write-Host "[1/6] Querying latest Pandaone release from GitHub..." -ForegroundColor Cyan
    try {
        $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$GITHUB_REPO/releases/latest" -Headers @{"User-Agent"="pandaone-installer"}
        $TARGET_VERSION = $release.tag_name -replace '^v', ''
        Write-Host "      Latest version: $TARGET_VERSION" -ForegroundColor Green
    } catch {
        Write-Host "[FAIL] Cannot query GitHub: $_" -ForegroundColor Red
        Write-Host "      Set `$env:PANDAONE_TARGET_VERSION=`"0.7.20`" and retry" -ForegroundColor Yellow
        exit 1
    }
}

# --- 2. 拼 wheel URL ---
$WHEEL_URL = "https://github.com/$GITHUB_REPO/releases/download/v$TARGET_VERSION/pandaone_guard-$TARGET_VERSION-py3-none-any.whl"
$WHEEL_PATH = Join-Path $env:TEMP "pandaone_guard-$TARGET_VERSION-py3-none-any.whl"

# --- 3. 卸老版 ---
Write-Host "[2/6] Uninstall old pandaone-guard..." -ForegroundColor Cyan
try {
    python -m pip uninstall pandaone-guard -y 2>&1 | Out-Null
    Write-Host "      OK" -ForegroundColor Green
} catch {
    Write-Host "      [WARN] uninstall error: $_" -ForegroundColor Yellow
}

# --- 4. 下 wheel ---
Write-Host "[3/6] Downloading $WHEEL_URL ..." -ForegroundColor Cyan
try {
    Invoke-WebRequest -Uri $WHEEL_URL -OutFile $WHEEL_PATH -UseBasicParsing
    $size = (Get-Item $WHEEL_PATH).Length
    Write-Host "      OK ($size bytes)" -ForegroundColor Green
} catch {
    Write-Host "[FAIL] Download error: $_" -ForegroundColor Red
    exit 1
}

# --- 5. 装新 wheel ---
Write-Host "[4/6] Installing pandaone-guard==$TARGET_VERSION ..." -ForegroundColor Cyan
try {
    python -m pip install --upgrade $WHEEL_PATH 2>&1 | Select-Object -Last 5
    Write-Host "      OK" -ForegroundColor Green
} catch {
    Write-Host "[FAIL] Install error: $_" -ForegroundColor Red
    exit 1
}

# --- 6. update-fingerprint (P0-2 改算法必跑) ---
Write-Host "[5/6] Updating fingerprint (P0-2 改算法, 必跑)..." -ForegroundColor Cyan
try {
    pandaone --update-fingerprint 0000
    Write-Host "      OK" -ForegroundColor Green
} catch {
    Write-Host "[FAIL] update-fingerprint error: $_" -ForegroundColor Red
    Write-Host "      手动跑: pandaone --update-fingerprint 0000" -ForegroundColor Yellow
}

# --- 7. 验 ---
Write-Host "[6/6] Verifying installation..." -ForegroundColor Cyan
try {
    $ver = pandaone --version
    Write-Host "      $ver" -ForegroundColor Green
} catch {
    Write-Host "[FAIL] verification error: $_" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "Pandaone $TARGET_VERSION 安装完成" -ForegroundColor Green
Write-Host "下一步 (可选): 装右键菜单 → pandaone install-context" -ForegroundColor Yellow
Write-Host "================================================" -ForegroundColor Cyan
