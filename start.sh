#!/usr/bin/env bash
# SQL Server → PostgreSQL Migration Platform — one-command launcher
# Usage: ./start.sh [--all|--api|--ui|--engine|--setup|--test|--help]
#   --all     API + UI + Go migration-engine (recommended)
# Author: Ravi Sharma  |  Copyright (c) 2026 Ravi Sharma  |  MIT License

# ── Colors ─────────────────────────────────────────────────────────────
RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

ok()   { echo -e "${GREEN}  ✓${RESET} $*"; }
warn() { echo -e "${YELLOW}  ⚠${RESET} $*"; }
err()  { echo -e "${RED}  ✗${RESET} $*" >&2; }
info() { echo -e "${CYAN}  →${RESET} $*"; }
step() { echo -e "\n${BOLD}$*${RESET}"; }

# ── Move to the directory this script lives in ──────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Banner ──────────────────────────────────────────────────────────────
echo -e "${CYAN}"
cat << 'BANNER'
  __  __ _      _     _                     ___        _    _
 |  \/  (_)__ _(_)___| |_ ___ _ _ ___  ___ / _ \ _ __ | |_(_)___ ___
 | |\/| | / _` | / -_)  _/ -_) '_/ -_)(_-<| (_) | '_ \|  _| / -_|_-<
 |_|  |_|_\__, |_\___|\__\___|_| \___/__/ \___/| .__/ \__|_\___/__/
          |___/                                 |_|
BANNER
echo -e "${RESET}${CYAN}  SQL Server → PostgreSQL Migration Platform  |  v0.2.0${RESET}"

# ══════════════════════════════════════════════════════════════════════
# STEP 1 — Locate Python 3.11+
# ══════════════════════════════════════════════════════════════════════
step "[1/3] Checking prerequisites..."

PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$candidate" &>/dev/null; then
        ver=$("$candidate" -c \
            "import sys; v=sys.version_info; print(f'{v.major}.{v.minor}.{v.micro}')" \
            2>/dev/null) || continue
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
            PYTHON="$candidate"
            ok "Python $ver  ($(command -v "$candidate"))"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    err "Python 3.11 or newer is required but was not found."
    echo ""
    echo "  Install it and re-run this script:"
    echo -e "    ${CYAN}macOS:${RESET}          brew install python@3.11"
    echo -e "    ${CYAN}Ubuntu/Debian:${RESET}  sudo apt install python3.11 python3.11-venv"
    echo -e "    ${CYAN}Other:${RESET}          https://www.python.org/downloads/"
    exit 1
fi

# Ensure the venv module is available
if ! "$PYTHON" -m venv --help &>/dev/null 2>&1; then
    err "Python venv module not available."
    echo "  On Ubuntu/Debian: sudo apt install python3-venv"
    exit 1
fi

# Node.js / npm — optional (needed only for the UI)
if command -v npm &>/dev/null; then
    ok "npm $(npm --version)  ($(command -v npm))"
else
    warn "Node.js / npm not found — UI will be skipped"
    echo "         Install from: https://nodejs.org"
fi

# Go — optional (needed for the migration-engine data plane)
if command -v go &>/dev/null; then
    ok "$(go version)"
else
    warn "Go not found — migration-engine will be skipped"
    echo "         Install Go 1.23+ from: https://go.dev/dl/"
fi

# ══════════════════════════════════════════════════════════════════════
# STEP 2 — Create / reuse virtual environment
# ══════════════════════════════════════════════════════════════════════
step "[2/3] Setting up Python virtual environment..."

VENV="$SCRIPT_DIR/.venv"
VENV_PYTHON="$VENV/bin/python"
VENV_PIP="$VENV/bin/pip"

if [ ! -f "$VENV_PYTHON" ]; then
    info "Creating .venv ..."
    "$PYTHON" -m venv "$VENV"
    ok "Virtual environment created  (.venv/)"
else
    ok "Using existing .venv"
fi

# Upgrade pip inside the venv (quiet; failures are non-fatal)
"$VENV_PIP" install --quiet --upgrade pip 2>/dev/null || true

# ══════════════════════════════════════════════════════════════════════
# STEP 3 — Hand off to start.py (it handles the rest)
#   start.py installs Python deps, npm deps, .env, then starts services.
# ══════════════════════════════════════════════════════════════════════
step "[3/3] Launching..."

exec "$VENV_PYTHON" "$SCRIPT_DIR/start.py" "$@"
