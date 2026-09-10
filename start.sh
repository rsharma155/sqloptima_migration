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
echo -e "${RESET}${CYAN}  SQL Server → PostgreSQL Migration Platform  |  v0.2.1${RESET}"

# ══════════════════════════════════════════════════════════════════════
# STEP 1 — Bootstrap prerequisites (Python venv module, Node, Go)
# ══════════════════════════════════════════════════════════════════════
step "[1/4] Bootstrapping prerequisites..."

BOOTSTRAP="$SCRIPT_DIR/scripts/bootstrap_prereqs.sh"
if [ -f "$BOOTSTRAP" ]; then
    chmod +x "$BOOTSTRAP" 2>/dev/null || true
    bash "$BOOTSTRAP" || warn "Some prerequisites could not be auto-installed"
else
    warn "bootstrap_prereqs.sh not found — skipping auto-install"
fi

PATH_ENV="${HOME}/.local/sqloptima/path.env"
if [ -f "$PATH_ENV" ]; then
    # shellcheck disable=SC1090
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in
            PATH=*) export PATH="${line#PATH=}" ;;
            GOROOT=*) export GOROOT="${line#GOROOT=}" ;;
        esac
    done <"$PATH_ENV"
fi

# ══════════════════════════════════════════════════════════════════════
# STEP 2 — Locate Python 3.11+
# ══════════════════════════════════════════════════════════════════════
step "[2/4] Checking prerequisites..."

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
    echo "  Re-run ./start.sh (auto-install) or install manually:"
    echo -e "    ${CYAN}Ubuntu/Debian:${RESET}  sudo apt install python3.12 python3.12-venv"
    echo -e "    ${CYAN}macOS:${RESET}          brew install python@3.12"
    exit 1
fi

python_venv_ready() {
    local py="$1"
    if ! "$py" -c "import ensurepip" &>/dev/null 2>&1; then
        return 1
    fi
    local tmp
    tmp=$(mktemp -d "${TMPDIR:-/tmp}/sqlo-venv.XXXXXX" 2>/dev/null) || return 1
    if "$py" -m venv "$tmp" &>/dev/null 2>&1; then
        rm -rf "$tmp"
        return 0
    fi
    rm -rf "$tmp"
    return 1
}

if ! python_venv_ready "$PYTHON"; then
    err "Python venv module not available."
    py_minor=$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "3")
    echo "  Re-run ./start.sh or: sudo apt install python${py_minor}-venv"
    exit 1
fi

if command -v npm &>/dev/null; then
    ok "npm $(npm --version)  ($(command -v npm))"
else
    warn "Node.js / npm still not available — UI will be skipped"
fi

if command -v go &>/dev/null; then
    ok "$(go version)"
else
    warn "Go still not available — migration-engine will be skipped"
fi

# ══════════════════════════════════════════════════════════════════════
# STEP 3 — Create / reuse virtual environment
# ══════════════════════════════════════════════════════════════════════
step "[3/4] Setting up Python virtual environment..."

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

"$VENV_PIP" install --quiet --upgrade pip 2>/dev/null || true

# ══════════════════════════════════════════════════════════════════════
# STEP 4 — Hand off to start.py (deps, .env, services)
# ══════════════════════════════════════════════════════════════════════
step "[4/4] Launching..."

export SQLOPTIMA_IN_VENV=1
exec "$VENV_PYTHON" "$SCRIPT_DIR/start.py" "$@"
