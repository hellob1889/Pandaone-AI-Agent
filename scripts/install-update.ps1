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
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "Pandaone v$TARGET_VERSION one-click upgrade" -ForegroundColor Green
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""

# --- 0. Resolve python interpreter ---
# $env:PANDAONE_PYTHON -> py.exe -3.11 -> system python (skip venv) -> PATH python
function Resolve-Python {
    if ($env:PANDAONE_PYTHON -and (Test-Path $env:PANDAONE_PYTHON)) {
        return $env:PANDAONE_PYTHON
    }
    $py = (Get-Command py.exe -ErrorAction SilentlyContinue)
    if ($py) {
        try {
            $ver = & py.exe -3.11 -c "import sys; print(sys.executable)" 2>$null
            if ($ver -and (Test-Path $ver)) {
                return $ver.Trim()
            }
        } catch {}
    }
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
    $first = (Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($first) { return $first.Path }
    throw "python.exe not found. Set `$env:PANDAONE_PYTHON explicitly."
}

$PYTHON = Resolve-Python
Write-Host "[*] Using python: $PYTHON" -ForegroundColor DarkGray

# --- 1. Build wheel URL ---
$WHEEL_URL = "https://github.com/$GITHUB_REPO/releases/download/v$TARGET_VERSION/pandaone_guard-$TARGET_VERSION-py3-none-any.whl"
$WHEEL_PATH = Join-Path $env:TEMP "pandaone_guard-$TARGET_VERSION-py3-none-any.whl"

# --- 2. Uninstall old version ---
Write-Host "[1/5] Uninstalling old pandaone-guard..." -ForegroundColor Cyan
$out = cmd /c "`"$PYTHON`" -m pip uninstall pandaone-guard -y 2>nul"
Write-Host "      OK" -ForegroundColor Green

# --- 3. Download wheel ---
Write-Host "[2/5] Downloading $WHEEL_URL ..." -ForegroundColor Cyan
$ProgressPreference = "SilentlyContinue"
try {
    Invoke-WebRequest -Uri $WHEEL_URL -OutFile $WHEEL_PATH -UseBasicParsing
    $size = (Get-Item $WHEEL_PATH).Length
    Write-Host "      OK ($size bytes)" -ForegroundColor Green
} catch {
    Write-Host "[FAIL] Download error: $_" -ForegroundColor Red
    exit 1
}

# --- 4. Install new wheel ---
Write-Host "[3/5] Installing pandaone-guard==$TARGET_VERSION ..." -ForegroundColor Cyan
$out = cmd /c "`"$PYTHON`" -m pip install --upgrade --force-reinstall `"$WHEEL_PATH`" 2>&1"
$out | Select-Object -Last 8
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] pip install exit=$LASTEXITCODE" -ForegroundColor Red
    exit 1
}
Write-Host "      OK" -ForegroundColor Green

# --- 5. update-fingerprint (mandatory: fingerprint algorithm changed in P0-2) ---
Write-Host "[4/5] Updating fingerprint (mandatory)..." -ForegroundColor Cyan
$out = cmd /c "`"$PYTHON`" -m pandaone --update-fingerprint 0000 2>&1"
$out | Select-Object -Last 5
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] update-fingerprint exit=$LASTEXITCODE" -ForegroundColor Red
    Write-Host "      Run manually: `"$PYTHON`" -m pandaone --update-fingerprint 0000" -ForegroundColor Yellow
} else {
    Write-Host "      OK" -ForegroundColor Green
}

# --- 6. Verify with doctor ---
Write-Host "[5/5] Verifying installation (doctor)..." -ForegroundColor Cyan
$out = cmd /c "`"$PYTHON`" -m pandaone doctor 2>&1"
$out | Select-Object -Last 20
if ($LASTEXITCODE -ne 0) {
    Write-Host "[WARN] doctor exit=$LASTEXITCODE (upgrade done, but self-check reported warnings)" -ForegroundColor Yellow
} else {
    Write-Host "      OK" -ForegroundColor Green
}

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "Pandaone $TARGET_VERSION installed" -ForegroundColor Green
Write-Host "Next (optional): install context menu -> $PYTHON -m pandaone install-context" -ForegroundColor Yellow
Write-Host "================================================" -ForegroundColor Cyan
