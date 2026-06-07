#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Migration Platform — one-command launcher for Windows.
.DESCRIPTION
  Checks prerequisites, creates an isolated Python virtual environment,
  installs all dependencies, and starts the SQL Server to PostgreSQL
  Migration Platform — no manual steps required.
.EXAMPLE
  .\start.ps1              # Interactive menu
  .\start.ps1 -all         # Start API + UI + Go engine (recommended)
  .\start.ps1 -engine      # Go migration-engine only
  .\start.ps1 -api         # API server only
  .\start.ps1 -ui          # UI dev server only
  .\start.ps1 -setup       # Install dependencies only
  .\start.ps1 -test        # Run the test suite
  .\start.ps1 1            # Non-interactive: start all
  .\start.ps1 2            # Non-interactive: API only
.NOTES
  If you see an execution-policy error, run once in an Admin PowerShell:
    Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
  Or bypass for a single run:
    powershell -ExecutionPolicy Bypass -File .\start.ps1
#>

param(
    [switch]$api,
    [switch]$ui,
    [switch]$all,
    [switch]$engine,
    [switch]$setup,
    [switch]$test,
    [switch]$help,
    [Parameter(Position=0)][ValidateRange(1,5)][int]$option = 0
)

# ── Helpers ────────────────────────────────────────────────────────────
function Write-Ok   { param($m) Write-Host "  v $m" -ForegroundColor Green }
function Write-Warn { param($m) Write-Host "  ! $m" -ForegroundColor Yellow }
function Write-Err  { param($m) Write-Host "  x $m" -ForegroundColor Red }
function Write-Info { param($m) Write-Host "  > $m" -ForegroundColor Cyan }
function Write-Step { param($m) Write-Host "`n$m" -ForegroundColor White }

# ── Execution-policy fix ───────────────────────────────────────────────
try {
    $pol = Get-ExecutionPolicy -Scope CurrentUser -ErrorAction Stop
} catch {
    $pol = Get-ExecutionPolicy -ErrorAction SilentlyContinue
}
if ($pol -in @('Restricted', 'Undefined', 'AllSigned')) {
    Write-Warn "PowerShell execution policy is '$pol'."
    Write-Host "  To fix permanently (recommended), run in an Admin PowerShell:" -ForegroundColor Yellow
    Write-Host "    Set-ExecutionPolicy RemoteSigned -Scope CurrentUser" -ForegroundColor Cyan
    Write-Host ""
    try { Set-ExecutionPolicy -Scope Process Bypass -Force -ErrorAction Stop }
    catch {}
}

# ── Navigate to the script's directory ────────────────────────────────
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# ══════════════════════════════════════════════════════════════════════
# STEP 1 — Locate Python 3.11+
# ══════════════════════════════════════════════════════════════════════
Write-Step "[1/3] Checking prerequisites..."

function Find-Python {
    # Try common command names first
    foreach ($cmd in @('python', 'python3')) {
        $exe = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($null -eq $exe) { continue }
        try {
            $ver = & $cmd -c "import sys; v=sys.version_info; print(f'{v.major}.{v.minor}.{v.micro}')" 2>$null
            if ($ver -match '^(\d+)\.(\d+)\.') {
                if ([int]$Matches[1] -ge 3 -and [int]$Matches[2] -ge 11) {
                    return @{ Cmd = $cmd; Ver = $ver }
                }
            }
        } catch {}
    }
    # Try Windows Python Launcher (py.exe) with explicit versions
    foreach ($minor in @('13','12','11')) {
        $pyExe = Get-Command 'py' -ErrorAction SilentlyContinue
        if ($null -eq $pyExe) { break }
        try {
            $ver = & py "-3.$minor" -c "import sys; v=sys.version_info; print(f'{v.major}.{v.minor}.{v.micro}')" 2>$null
            if ($ver -match '^\d+\.\d+\.') {
                return @{ Cmd = "py -3.$minor"; Ver = $ver }
            }
        } catch {}
    }
    return $null
}

$pyInfo = Find-Python
if ($null -eq $pyInfo) {
    Write-Err "Python 3.11 or newer is required but was not found."
    Write-Host ""
    Write-Host "  Download from: https://www.python.org/downloads/" -ForegroundColor Cyan
    Write-Host "  (Check 'Add Python to PATH' during installation)" -ForegroundColor Yellow
    Read-Host "`nPress Enter to exit"
    exit 1
}
Write-Ok "Python $($pyInfo.Ver)"

# Npm / Node.js — optional (required only for the UI)
$NpmCmd = Get-Command npm -ErrorAction SilentlyContinue
if ($null -ne $NpmCmd) {
    Write-Ok "npm $(npm --version 2>$null)"
} else {
    Write-Warn "Node.js / npm not found — UI will be skipped"
    Write-Host "         Install from: https://nodejs.org" -ForegroundColor Cyan
}

# Go — optional (required for migration-engine)
$GoCmd = Get-Command go -ErrorAction SilentlyContinue
if ($null -ne $GoCmd) {
    Write-Ok "$(go version 2>$null)"
} else {
    Write-Warn "Go not found — migration-engine will be skipped"
    Write-Host "         Install Go 1.23+ from: https://go.dev/dl/" -ForegroundColor Cyan
}

# ══════════════════════════════════════════════════════════════════════
# STEP 2 — Create / reuse virtual environment
# ══════════════════════════════════════════════════════════════════════
Write-Step "[2/3] Setting up Python virtual environment..."

$VenvDir    = Join-Path $ScriptDir ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvPip    = Join-Path $VenvDir "Scripts\pip.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Info "Creating .venv ..."
    $pyCmd = $pyInfo.Cmd
    if ($pyCmd -match '^py\s+-') {
        # e.g. "py -3.11"  →  py, -3.11
        $parts = $pyCmd -split '\s+'
        & $parts[0] $parts[1] -m venv $VenvDir
    } else {
        & $pyCmd -m venv $VenvDir
    }
    if (-not (Test-Path $VenvPython)) {
        Write-Err "Failed to create virtual environment."
        exit 1
    }
    Write-Ok "Virtual environment created  (.venv\)"
} else {
    Write-Ok "Using existing .venv"
}

# Upgrade pip in the venv
& $VenvPip install --quiet --upgrade pip 2>$null | Out-Null

# ══════════════════════════════════════════════════════════════════════
# STEP 3 — Hand off to start.py (it handles the rest)
#   start.py installs Python deps, npm deps, .env, then starts services.
# ══════════════════════════════════════════════════════════════════════
Write-Step "[3/3] Launching..."
Write-Host ""

# Build the argument list to forward to start.py
$fwdArgs = [System.Collections.Generic.List[string]]::new()
if ($api)            { $fwdArgs.Add('--api') }
if ($ui)             { $fwdArgs.Add('--ui') }
if ($all)            { $fwdArgs.Add('--all') }
if ($engine)         { $fwdArgs.Add('--engine') }
if ($setup)          { $fwdArgs.Add('--setup') }
if ($test)           { $fwdArgs.Add('--test') }
if ($help)           { $fwdArgs.Add('--help') }
if ($option -gt 0)   { $fwdArgs.Add($option.ToString()) }

$startPy = Join-Path $ScriptDir "start.py"
& $VenvPython $startPy @fwdArgs
exit $LASTEXITCODE
