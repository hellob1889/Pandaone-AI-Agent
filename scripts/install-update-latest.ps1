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
#
# 或指定 python (PATH 里有 venv python 但想用 system python):
#   $env:PANDAONE_PYTHON="C:\Users\you\AppData\Local\Programs\Python\Python311\python.exe"; irm ... | iex
# ============================================================

$ErrorActionPreference = "Stop"
$GITHUB_REPO = "hellob1889/Pandaone-AI-Agent"
$TARGET_VERSION = $env:PANDAONE_TARGET_VERSION  # 可选, 默认取最新

# --- 0. 解析 python 解释器 ---
# 优先: $env:PANDAONE_PYTHON → py.exe -3.11 (Windows launcher) → 系统 python (跳 venv) → PATH python
function Resolve-Python {
    if ($env:PANDAONE_PYTHON -and (Test-Path $env:PANDAONE_PYTHON)) {
        return $env:PANDAONE_PYTHON
    }
    # Windows Python launcher
    $py = (Get-Command py.exe -ErrorAction SilentlyContinue)
    if ($py) {
        try {
            $ver = & py.exe -3.11 -c "import sys; print(sys.executable)" 2>$null
            if ($ver -and (Test-Path $ver)) {
                return $ver.Trim()
            }
        } catch {}
    }
    # 系统 python (跳 venv/Scripts/python.exe)
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "C:\Python311\python.exe",
        "C:\Python312\python.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }
    # Fallback: PATH 第一个 python.exe
    $first = (Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($first) { return $first.Path }
    throw "找不到 python.exe, 请设置 `$env:PANDAONE_PYTHON 显式指向"
}

$PYTHON = Resolve-Python
Write-Host "[*] Using python: $PYTHON" -ForegroundColor DarkGray

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
$out = cmd /c "`"$PYTHON`" -m pip uninstall pandaone-guard -y 2>nul"
Write-Host "      OK" -ForegroundColor Green

# --- 4. 下 wheel ---
Write-Host "[3/6] Downloading $WHEEL_URL ..." -ForegroundColor Cyan
$ProgressPreference = "SilentlyContinue"
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
$out = cmd /c "`"$PYTHON`" -m pip install --upgrade --force-reinstall `"$WHEEL_PATH`" 2>&1"
$out | Select-Object -Last 8
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] pip install exit=$LASTEXITCODE" -ForegroundColor Red
    exit 1
}
Write-Host "      OK" -ForegroundColor Green

# --- 6. update-fingerprint (P0-2 改算法必跑) ---
Write-Host "[5/6] Updating fingerprint (P0-2 改算法, 必跑)..." -ForegroundColor Cyan
$out = cmd /c "`"$PYTHON`" -m pandaone --update-fingerprint 0000 2>&1"
$out | Select-Object -Last 5
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] update-fingerprint exit=$LASTEXITCODE" -ForegroundColor Red
    Write-Host "      手动跑: `"$PYTHON`" -m pandaone --update-fingerprint 0000" -ForegroundColor Yellow
} else {
    Write-Host "      OK" -ForegroundColor Green
}

# --- 7. 验 ---
Write-Host "[6/6] Verifying installation..." -ForegroundColor Cyan
$ver = cmd /c "`"$PYTHON`" -m pandaone --version 2>&1"
Write-Host "      $ver" -ForegroundColor Green

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "Pandaone $TARGET_VERSION 安装完成" -ForegroundColor Green
Write-Host "下一步 (可选): 装右键菜单 → $PYTHON -m pandaone install-context" -ForegroundColor Yellow
Write-Host "================================================" -ForegroundColor Cyan
