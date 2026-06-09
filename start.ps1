#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Migration Platform — one-command launcher for Windows.
.DESCRIPTION
  Auto-installs prerequisites (Python, Node.js, Go), creates a virtual
  environment, installs project dependencies, and starts the platform.
.EXAMPLE
  .\start.ps1              # Interactive menu
  .\start.ps1 -all         # Start API + UI + Go engine (recommended)
  .\start.ps1 -engine      # Go migration-engine only
  .\start.ps1 -api         # API server only
  .\start.ps1 -ui          # UI dev server only
  .\start.ps1 -setup       # Install dependencies only
  .\start.ps1 -test        # Run the test suite
  .\start.ps1 1            # Non-interactive: start all
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
# STEP 1 — Bootstrap prerequisites (Python, Node, Go)
# ══════════════════════════════════════════════════════════════════════
Write-Step "[1/4] Bootstrapping prerequisites..."

$Bootstrap = Join-Path $ScriptDir "scripts\bootstrap_prereqs.ps1"
if (Test-Path $Bootstrap) {
    try {
        & $Bootstrap
    } catch {
        Write-Warn "Some prerequisites could not be auto-installed: $_"
    }
} else {
    Write-Warn "bootstrap_prereqs.ps1 not found — skipping auto-install"
}

$PathEnvFile = Join-Path $env:LOCALAPPDATA "sqloptima\path.env"
if (Test-Path $PathEnvFile) {
    Get-Content $PathEnvFile | ForEach-Object {
        if ($_ -match '^PATH=(.+)$') { $env:Path = $Matches[1] }
        elseif ($_ -match '^GOROOT=(.+)$') { $env:GOROOT = $Matches[1] }
    }
}

# ══════════════════════════════════════════════════════════════════════
# STEP 2 — Locate Python 3.11+
# ══════════════════════════════════════════════════════════════════════
Write-Step "[2/4] Checking prerequisites..."

function Find-Python {
    foreach ($cmd in @('python', 'python3')) {
        $exe = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($null -eq $exe) { continue }
        try {
            $ver = & $cmd -c 'import sys; v=sys.version_info; print(f"{v.major}.{v.minor}.{v.micro}")' 2>$null
            if ($ver -match '^(\d+)\.(\d+)\.') {
                if ([int]$Matches[1] -ge 3 -and [int]$Matches[2] -ge 11) {
                    return @{ Cmd = $cmd; Ver = $ver }
                }
            }
        } catch {}
    }
    foreach ($minor in @('13','12','11')) {
        $pyExe = Get-Command 'py' -ErrorAction SilentlyContinue
        if ($null -eq $pyExe) { break }
        try {
            $ver = & py "-3.$minor" -c 'import sys; v=sys.version_info; print(f"{v.major}.{v.minor}.{v.micro}")' 2>$null
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
    Write-Host "  Re-run .\start.ps1 (auto-install) or download from:" -ForegroundColor Cyan
    Write-Host "  https://www.python.org/downloads/ (check Add Python to PATH)" -ForegroundColor Yellow
    Read-Host "`nPress Enter to exit"
    exit 1
}
Write-Ok "Python $($pyInfo.Ver)"

$NpmCmd = Get-Command npm -ErrorAction SilentlyContinue
if ($null -ne $NpmCmd) {
    Write-Ok "npm $(npm --version 2>$null)"
} else {
    Write-Warn "Node.js / npm still not available — UI will be skipped"
}

$GoCmd = Get-Command go -ErrorAction SilentlyContinue
if ($null -ne $GoCmd) {
    Write-Ok "$(go version 2>$null)"
} else {
    Write-Warn "Go still not available — migration-engine will be skipped"
}

# ══════════════════════════════════════════════════════════════════════
# STEP 3 — Create / reuse virtual environment
# ══════════════════════════════════════════════════════════════════════
Write-Step "[3/4] Setting up Python virtual environment..."

$VenvDir    = Join-Path $ScriptDir ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvPip    = Join-Path $VenvDir "Scripts\pip.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Info "Creating .venv ..."
    $pyCmd = $pyInfo.Cmd
    if ($pyCmd -match '^py\s+-') {
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

& $VenvPip install --quiet --upgrade pip 2>$null | Out-Null

# ══════════════════════════════════════════════════════════════════════
# STEP 4 — Hand off to start.py
# ══════════════════════════════════════════════════════════════════════
Write-Step "[4/4] Launching..."
Write-Host ""

$fwdArgs = [System.Collections.Generic.List[string]]::new()
if ($api)            { $fwdArgs.Add('--api') }
if ($ui)             { $fwdArgs.Add('--ui') }
if ($all)            { $fwdArgs.Add('--all') }
if ($engine)         { $fwdArgs.Add('--engine') }
if ($setup)          { $fwdArgs.Add('--setup') }
if ($test)           { $fwdArgs.Add('--test') }
if ($help)           { $fwdArgs.Add('--help') }
if ($option -gt 0)   { $fwdArgs.Add($option.ToString()) }

$env:SQLOPTIMA_IN_VENV = "1"
$startPy = Join-Path $ScriptDir "start.py"
& $VenvPython $startPy @fwdArgs
exit $LASTEXITCODE
