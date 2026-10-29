# install.ps1 - Pandaone AI Agent one-shot installer (Windows)
# ====================================================
# Adversarial review: ensures the environment is ready
# right after the user clones the repo.
#
# Steps:
#   1. Check Python version (>= 3.10)
#   2. Locate git (PATH or candidate dirs)
#   3. Uninstall stale pandaone from site-packages
#   4. python -m pip install -e .  (--no-build-isolation)
#   5. Verify pandaone works (python -m pandaone --version)
#   6. Run doctor.py --fix --persist-path
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/install.ps1
#   .\scripts\install.ps1
#
# First principles:
#   - UX: clone -> 1 command -> works
#   - Don't assume environment (git path, Python path, pip name)
#   - Fail loudly with clear next-step hints, never silent
#
# NOTE: Pure ASCII (no ANSI colors, no emojis) because
# Windows PowerShell 5 + UTF-8 source file has known encoding
# issues with ESC bytes. Portability over prettiness.

[CmdletBinding()]
param(
    [switch]$SkipInstall,
    [switch]$SkipDoctor,
    [switch]$SkipMcp,
    [switch]$Force,
    [switch]$Help
)

# ============================================================
# Config
# ============================================================
$ErrorActionPreference = "Stop"
$MIN_PYTHON_MAJOR = 3
$MIN_PYTHON_MINOR = 10
$REPO_ROOT = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$SCRIPTS_DIR = Join-Path $REPO_ROOT "scripts"

# Common Windows git install locations
$WINDOWS_GIT_CANDIDATES = @(

    "D:\Program Files\Git\cmd",
    "C:\Program Files\Git\cmd",
    "C:\Program Files (x86)\Git\cmd",
    "C:\Program Files\Git\bin"
)

# ============================================================
# Helpers
# ============================================================
function Write-Banner {
    Write-Host ""
    Write-Host "================================================================"
    Write-Host " Pandaone installer - install.ps1"
    Write-Host " Repo: $REPO_ROOT"
    Write-Host "================================================================"
    Write-Host ""
}

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "[STEP] $Message"
}

function Write-OK {
    param([string]$Message)
    Write-Host "  [OK]   $Message"
}

function Write-Warn {
    param([string]$Message)
    Write-Host "  [WARN] $Message"
}

function Write-Fail {
    param([string]$Message)
    Write-Host "  [FAIL] $Message"
}

function Write-Info {
    param([string]$Message)
    Write-Host "  [INFO] $Message"
}

# ============================================================
# Checks
# ============================================================
function Test-PythonVersion {
    Write-Step "1/6 Detect Python"
    foreach ($cmd in @("python", "python3", "py")) {
        $found = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($found) {
            $versionOutput = & $cmd "--version" 2>&1
            if ($versionOutput -match "Python (\d+)\.(\d+)\.(\d+)") {
                $major = [int]$Matches[1]
                $minor = [int]$Matches[2]
                if ($major -gt $MIN_PYTHON_MAJOR -or ($major -eq $MIN_PYTHON_MAJOR -and $minor -ge $MIN_PYTHON_MINOR)) {
                    Write-OK "$versionOutput (>=$MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR)"
                    return $cmd
                } else {
                    Write-Warn "$versionOutput (need >=$MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR)"
                }
            }
        }
    }
    Write-Fail "Python >=$MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR not found"
    Write-Host "        Install: https://www.python.org/downloads/"
    Write-Host "        IMPORTANT: tick 'Add Python to PATH'"
    return $null
}

function Find-GitPath {
    Write-Step "2/6 Locate git"
    $git = Get-Command "git" -ErrorAction SilentlyContinue
    if ($git) {
        Write-OK "git: $($git.Source)"
        return $git.Source
    }
    Write-Warn "git not in PATH, scanning candidate dirs..."
    foreach ($cand in $WINDOWS_GIT_CANDIDATES) {
        $exe = Join-Path $cand "git.exe"
        if (Test-Path $exe) {
            Write-OK "Found git: $exe"
            $env:PATH = "$cand;$env:PATH"
            Write-Info "Added to PATH for this session only"
            return $exe
        }
    }
    Write-Fail "git.exe not found"
    Write-Host "        Install: https://git-scm.com/download/win"
    Write-Host "        Or winget: winget install Git.Git"
    Write-Host "        Or choco:  choco install git"
    return $null
}

function Uninstall-StalePandax {
    Write-Step "3/6 Remove stale pandaone from site-packages"
    $stale = & pip show pandaone 2>&1 | Out-String
    if ($stale -match "Name: pandaone") {
        Write-Warn "Stale pandaone installed in site-packages"
        $versionLine = ($stale | Select-String "Version:")
        if ($versionLine) {
            Write-Info ("version: " + $versionLine.ToString().Trim())
        }
        $answer = "y"
        if (-not $Force) {
            $answer = Read-Host "        Uninstall? (y/N, default y)"
            if ([string]::IsNullOrEmpty($answer)) { $answer = "y" }
        }
        if ($answer -match "^[Yy]") {
            pip uninstall pandaone -y 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-OK "Uninstalled"
            } else {
                Write-Warn "Uninstall failed (may not matter, continuing)"
            }
        } else {
            Write-Info "Keeping stale version (version conflict risk accepted)"
        }
    } else {
        Write-OK "No stale pandaone"
    }
}

function Install-PandaxEditable {
    Write-Step "4/6 Install local source (editable)"
    Write-Info "cd $REPO_ROOT"
    Push-Location $REPO_ROOT
    try {
        $output = python -m pip install -e . --no-build-isolation 2>&1 | Out-String
        Write-Host $output
        if ($LASTEXITCODE -eq 0) {
            Write-OK "Local install succeeded"
        } else {
            Write-Fail "pip install failed (exit $LASTEXITCODE)"
            Write-Host $output
            return $false
        }
    } finally {
        Pop-Location
    }
    return $true
}

function Verify-PandaxInstall {
    Write-Step "5/6 Verify pandaone works"
    try {
        # Avoid PowerShell parsing Python's __file__ / __version__ as object members
        $check = python -m pandaone --version 2>&1 | Out-String
        if ($check -match "pandaone v\d") {
            Write-Host $check
            Write-OK "pandaone works (python -m pandaone)"
        } else {
            Write-Fail "pandaone not importable"
            Write-Host $check
            return $false
        }
    } catch {
        Write-Fail "verify exception: $_"
        return $false
    }
    return $true
}

function Run-DoctorAndFix {
    Write-Step "6/6 Run doctor.py --fix --persist-path (auto-fix + persist PATH)"
    $doctor = Join-Path $SCRIPTS_DIR "doctor.py"
    if (-not (Test-Path $doctor)) {
        Write-Fail "Missing $doctor"
        return $false
    }
    # Delegate remaining issues (deps / setuptools / fingerprint / PATH persist)
    # to doctor.py --fix --persist-path so we don't duplicate logic.
    python $doctor --fix --persist-path
    return ($LASTEXITCODE -eq 0)
}

function Show-Help {
    Write-Host "Usage: .\scripts\install.ps1 [options]"
    Write-Host ""
    Write-Host "Options:"
    Write-Host "  -SkipInstall   Skip pip install, only run doctor"
    Write-Host "  -SkipDoctor    Skip doctor verification"
    Write-Host "  -Force         Auto-answer yes (uninstall stale pandaone, etc)"
    Write-Host "  -Help          Show this help"
    Write-Host ""
    Write-Host "Examples:"
    Write-Host "  .\scripts\install.ps1                  # full install"
    Write-Host "  .\scripts\install.ps1 -SkipInstall     # diagnose only"
    Write-Host "  .\scripts\install.ps1 -Force           # unattended"
}

# ============================================================
# Main
# ============================================================
if ($Help) {
    Show-Help
    exit 0
}

Write-Banner

$startTime = Get-Date

# Step 1: Python
$python = Test-PythonVersion
if (-not $python) {
    Write-Host ""
    Write-Fail "Python check failed, cannot continue"
    exit 1
}

# Step 2: Git
$git = Find-GitPath
if (-not $git) {
    Write-Host ""
    Write-Warn "git not found, some features (rollback, pre-commit hook) limited"
    Write-Info "Can continue, but git is recommended"
    $answer = "N"
    if (-not $Force) {
        $answer = Read-Host "        Continue? (y/N)"
    } else {
        $answer = "y"
    }
    if ($answer -notmatch "^[Yy]") {
        exit 1
    }
}

if (-not $SkipInstall) {
    # Step 3: Uninstall stale
    Uninstall-StalePandax

    # Step 4: Install
    $installed = Install-PandaxEditable
    if (-not $installed) {
        Write-Host ""
        Write-Fail "Install failed"
        exit 1
    }

    # Step 5: Verify
    $verified = Verify-PandaxInstall
    if (-not $verified) {
        Write-Host ""
        Write-Fail "Verify failed"
        exit 1
    }
}

if (-not $SkipDoctor) {
    # Step 6: Auto-fix via doctor.py + persist PATH
    $doctorOk = Run-DoctorAndFix
    if (-not $doctorOk) {
        Write-Host ""
        Write-Warn "doctor.py --fix reported remaining issues (see above)"
        Write-Info "Re-run after addressing them: python scripts/doctor.py"
    }
}

$duration = (Get-Date) - $startTime
Write-Host ""
Write-Host "================================================================"
Write-Host " Install done in $($duration.ToString('mm\:ss'))"
Write-Host "================================================================"
Write-Host ""
# ---- 注册 MCP server（可用 -SkipMcp 跳过）----
if (-not $SkipMcp) {
    Write-Host "[MCP] 注册 MCP server 到 IDE 配置（Claude Desktop / Cursor / Trae）..." -ForegroundColor Cyan
    python -m pandaone install-mcp --client auto
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  MCP 注册完成" -ForegroundColor Green
    } else {
        Write-Host "  MCP 注册失败，可手动执行: pandaone install-mcp" -ForegroundColor Yellow
    }
} else {
    Write-Host "[SKIP] MCP 注册 (per -SkipMcp)" -ForegroundColor DarkGray
}

Write-Host "Next steps:"
Write-Host "  pandaone install-mcp         # register MCP server in IDE configs"
Write-Host "  python -m pandaone --version         # verify CLI"
Write-Host "  python scripts/doctor.py           # detailed diagnosis"
Write-Host "  python -m pytest tests/ -q         # run all tests"
Write-Host ""

exit 0
