#!/usr/bin/env python3
"""
Migration Platform — Cross-platform one-command launcher.
Supports Windows (PowerShell), Linux, and macOS.

Usage:
    python start.py              # Interactive menu
    python start.py --all        # Start API + UI (default)
    python start.py --api        # Start API server only
    python start.py --ui         # Start UI dev server only
    python start.py --setup      # Install deps only (no server start)
    python start.py --test       # Run tests
    python start.py --help       # Show this help
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UI_DIR = ROOT / "apps" / "ui"
ENGINE_DIR = ROOT / "engine-go"
DATA_DIR = ROOT / "data"
ENV_FILE = ROOT / ".env"
ENV_ENCODING = "utf-8"
PYPROJECT = ROOT / "pyproject.toml"
REQUIREMENTS = ROOT / "requirements.txt"

IS_WINDOWS = sys.platform == "win32"
VENV_DIR = ROOT / ".venv"
VENV_PYTHON = (VENV_DIR / "Scripts" / "python.exe") if IS_WINDOWS else (VENV_DIR / "bin" / "python")
PYTHON = sys.executable
NPM = shutil.which("npm") or shutil.which("npm.cmd")

# ── Colors ────────────────────────────────────────────────────────────

class C:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    END = "\033[0m"

def _c(code: str, text: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"{code}{text}{C.END}"


def print_banner():
    banner = rf"""{C.CYAN}
  ___  ___  _       ___       _   _               __  __ _               _   _
 / __|/ _ \| |     / _ \ _ __| |_(_)_ __  __ _  |  \/  (_)__ _ _ _ __ _| |_(_)___ _ _
 \__ \ (_) | |__  | (_) | '_ \  _| | '  \/ _` | | |\/| | / _` | '_/ _` |  _| / _ \ ' \
 |___/\__\_\____|  \___/| .__/\__|_|_|_|_\__,_| |_|  |_|_\__, |_| \__,_|\__|_\___/_||_|
                        |_|                               |___/
{C.CYAN}{C.DIM}  SQL Server → PostgreSQL  |  DDD + Clean Arch  |  v0.2.0{C.END}
    """
    print(banner)


# ── Prerequisites ─────────────────────────────────────────────────────

def _bootstrap_path_env_file() -> Path:
    if IS_WINDOWS:
        local = os.environ.get("LOCALAPPDATA", "")
        return Path(local) / "sqloptima" / "path.env" if local else Path.home() / "sqloptima" / "path.env"
    return Path.home() / ".local" / "sqloptima" / "path.env"


def _load_bootstrap_path() -> None:
    """Apply PATH/GOROOT written by scripts/bootstrap_prereqs.*."""
    path_env = _bootstrap_path_env_file()
    if not path_env.is_file():
        return
    for line in path_env.read_text().splitlines():
        if line.startswith("PATH="):
            os.environ["PATH"] = line[5:]
        elif line.startswith("GOROOT="):
            os.environ["GOROOT"] = line[7:]


def _refresh_tool_paths() -> None:
    global NPM
    NPM = shutil.which("npm") or shutil.which("npm.cmd")


def _pip_available() -> bool:
    try:
        subprocess.run(
            [PYTHON, "-m", "pip", "--version"],
            capture_output=True,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return False


def _run_bootstrap_prereqs() -> None:
    """Invoke platform bootstrap script to install Node, Go, Python venv support."""
    if os.environ.get("SQLOPTIMA_BOOTSTRAP_DONE") == "1":
        return
    
    # Check if --yes was passed in sys.argv
    auto_yes = "--yes" in sys.argv or "-y" in sys.argv

    if IS_WINDOWS:
        script = ROOT / "scripts" / "bootstrap_prereqs.ps1"
        if not script.is_file():
            return
        print(f"\n {C.BOLD}Checking prerequisites (Windows)...{C.END}")
        args = ["pwsh", "-NoProfile", "-File", str(script)]
        if auto_yes:
            args.append("-Yes")
        subprocess.run(args, cwd=ROOT, check=False)
    else:
        script = ROOT / "scripts" / "bootstrap_prereqs.sh"
        if not script.is_file():
            return
        print(f"\n {C.BOLD}Checking prerequisites...{C.END}")
        args = ["bash", str(script)]
        if auto_yes:
            args.append("--yes")
        subprocess.run(args, cwd=ROOT, check=False)
    os.environ["SQLOPTIMA_BOOTSTRAP_DONE"] = "1"
    _load_bootstrap_path()
    _refresh_tool_paths()


def _in_project_venv() -> bool:
    if os.environ.get("SQLOPTIMA_IN_VENV") == "1":
        return True
    try:
        return Path(sys.executable).resolve() == VENV_PYTHON.resolve()
    except OSError:
        return False


def ensure_project_venv() -> None:
    """Create .venv when needed and re-exec start.py inside it (bundled pip)."""
    if _in_project_venv():
        return

    if not VENV_PYTHON.is_file():
        py = sys.executable
        v = sys.version_info
        if v.major < 3 or (v.major == 3 and v.minor < 11):
            print(f" {C.RED}✗{C.END} Python >= 3.11 required (found {v.major}.{v.minor}.{v.micro})")
            print(f"   Run {C.BOLD}./start.sh --all{C.END} (Linux/macOS) or {C.BOLD}.\\start.ps1 -all{C.END} (Windows)")
            sys.exit(1)
        print(f"\n {C.CYAN}→{C.END} Creating project virtual environment (.venv)...")
        try:
            subprocess.check_call([py, "-m", "venv", str(VENV_DIR)], cwd=ROOT)
        except subprocess.CalledProcessError:
            _run_bootstrap_prereqs()
            try:
                subprocess.check_call([py, "-m", "venv", str(VENV_DIR)], cwd=ROOT)
            except subprocess.CalledProcessError:
                if not IS_WINDOWS:
                    minor = f"{v.major}.{v.minor}"
                    print(f"\n {C.RED}✗{C.END} Failed to create .venv — the 'venv' module might be missing.")
                    print(f"   Run this command to fix it: {C.BOLD}sudo apt install python{minor}-venv{C.END}")
                    print(f"   Then re-run: {C.BOLD}./start.sh --all{C.END}")
                else:
                    print(f"\n {C.RED}✗{C.END} Failed to create .venv.")
                sys.exit(1)

    if not VENV_PYTHON.is_file():
        launcher = ".\\start.ps1 -all" if IS_WINDOWS else "./start.sh --all"
        print(f" {C.RED}✗{C.END} Could not create .venv — use the platform launcher:")
        print(f"   {C.BOLD}{launcher}{C.END}")
        sys.exit(1)

    os.environ["SQLOPTIMA_IN_VENV"] = "1"
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(ROOT / "start.py"), *sys.argv[1:]])


def check_python() -> bool:
    v = sys.version_info
    if v.major < 3 or (v.major == 3 and v.minor < 11):
        print(f" {C.RED}✗{C.END} Python >= 3.11 required (found {v.major}.{v.minor}.{v.micro})")
        return False
    print(f" {C.GREEN}✓{C.END} Python {v.major}.{v.minor}.{v.micro}")
    return True


def check_node() -> bool:
    _refresh_tool_paths()
    if not NPM:
        _run_bootstrap_prereqs()
        _refresh_tool_paths()
    if not NPM:
        print(f" {C.YELLOW}⚠{C.END} Node.js/npm not found — UI will not start")
        return False
    try:
        out = subprocess.check_output([NPM, "--version"], text=True).strip()
        print(f" {C.GREEN}✓{C.END} npm v{out}")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        print(f" {C.YELLOW}⚠{C.END} npm not available — UI will not start")
        return False


def check_go() -> bool:
    go = shutil.which("go")
    if not go:
        _run_bootstrap_prereqs()
        go = shutil.which("go")
    if not go:
        print(f" {C.YELLOW}⚠{C.END} Go toolchain not found — migration-engine will not start")
        print(f"   Install Go 1.23+ from https://go.dev/dl/ or re-run ./start.sh / .\\start.ps1")
        return False
    try:
        out = subprocess.check_output([go, "version"], text=True).strip()
        print(f" {C.GREEN}✓{C.END} {out}")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        print(f" {C.YELLOW}⚠{C.END} Go not available — migration-engine will not start")
        return False


# ── Environment ───────────────────────────────────────────────────────

DEFAULT_ENV = """# SQL Optima Migration - Environment Configuration
# Copy this to .env and adjust for your environment.

MIGRATION_MASTER_KEY={master_key}
MIGRATION_JWT_SECRET={jwt_secret}

# Source (SQL Server)
MIGRATION_SOURCE_HOST=localhost
MIGRATION_SOURCE_PORT=1433
MIGRATION_SOURCE_DATABASE=source_db
MIGRATION_SOURCE_USER=sa
MIGRATION_SOURCE_PASSWORD=
# Set to true for SQL Server instances with self-signed TLS certificates (dev/test only)
MIGRATION_SOURCE_TRUST_CERT=false

# Target (PostgreSQL)
MIGRATION_TARGET_HOST=localhost
MIGRATION_TARGET_PORT=5432
MIGRATION_TARGET_DATABASE=target_db
MIGRATION_TARGET_USER=postgres
MIGRATION_TARGET_PASSWORD=

# Optional
MIGRATION_JOBS_FILE=migration_jobs.json

# Metadata database (postgres_checklist container - auto-started by start.py)
METADATA_DB_URL=postgresql+asyncpg://postgres:postgres@localhost:5555/migration_checklist

# Go migration-engine (start.py backfills if missing)
MIGRATION_DATABASE_METADATA_URL=postgresql://postgres:postgres@localhost:5555/migration_checklist
MIGRATION_QUEUE_PATH=data/migration_queue.bbolt
"""


def _random_key(length: int = 32) -> str:
    import base64
    import secrets
    return base64.urlsafe_b64encode(secrets.token_bytes(length)).decode()


def _read_env_file() -> str:
    """Read .env as UTF-8, falling back to Windows locale encodings when needed."""
    if not ENV_FILE.exists():
        return ""
    try:
        return ENV_FILE.read_text(encoding=ENV_ENCODING)
    except UnicodeDecodeError:
        for enc in ("cp1252", "latin-1"):
            try:
                return ENV_FILE.read_text(encoding=enc)
            except UnicodeDecodeError:
                continue
        return ENV_FILE.read_text(encoding=ENV_ENCODING, errors="replace")


def _write_env_file(text: str) -> None:
    """Always persist .env as UTF-8 (Starlette/slowapi require UTF-8 on read)."""
    ENV_FILE.write_text(text, encoding=ENV_ENCODING, newline="\n")


def _repair_env_encoding() -> bool:
    """Rewrite legacy Windows-locale .env files as UTF-8."""
    if not ENV_FILE.exists():
        return False
    try:
        ENV_FILE.read_text(encoding=ENV_ENCODING)
        return False
    except UnicodeDecodeError:
        pass
    _write_env_file(_read_env_file())
    print(f" {C.YELLOW}✦{C.END} Repaired .env encoding (saved as UTF-8 for Windows compatibility)")
    return True


_ENV_BACKFILL: dict[str, str] = {
    "MIGRATION_SOURCE_TRUST_CERT": "false",
    "METADATA_DB_URL": "postgresql+asyncpg://postgres:postgres@localhost:5555/migration_checklist",
    "MIGRATION_DATABASE_METADATA_URL": "postgresql://postgres:postgres@localhost:5555/migration_checklist",
    "MIGRATION_QUEUE_PATH": "data/migration_queue.bbolt",
}


def _backfill_env_keys() -> list[str]:
    """Append missing template keys to an existing .env without overwriting values."""
    if not ENV_FILE.exists():
        return []
    lines = _read_env_file().splitlines()
    existing = {
        ln.partition("=")[0].strip()
        for ln in lines
        if ln.strip() and not ln.strip().startswith("#") and "=" in ln
    }
    added: list[str] = []
    for key, default in _ENV_BACKFILL.items():
        if key in existing:
            continue
        lines.append(f"{key}={default}")
        added.append(key)
    if added:
        _write_env_file("\n".join(lines) + "\n")
    return added


def ensure_env():
    if ENV_FILE.exists():
        _repair_env_encoding()
        added = _backfill_env_keys()
        print(f" {C.GREEN}✓{C.END} .env file exists")
        if added:
            print(f" {C.YELLOW}✦{C.END} Added missing keys to .env: {', '.join(added)}")
        return

    master_key = _random_key()
    jwt_secret = _random_key()
    _write_env_file(DEFAULT_ENV.format(master_key=master_key, jwt_secret=jwt_secret))
    print(f" {C.YELLOW}✦{C.END} Created .env with generated keys")
    print(f"   MIGRATION_MASTER_KEY={master_key}")
    print(f"   MIGRATION_JWT_SECRET={jwt_secret}")
    print(f"   Open the app in your browser to complete first-time admin setup.")


def load_env():
    """Load .env into os.environ (simple parser, no dotenv dependency)."""
    if not ENV_FILE.exists():
        return
    _repair_env_encoding()
    for line in _read_env_file().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("\"'")
        if key:
            os.environ.setdefault(key, val)
    _sync_go_engine_env()


def _metadata_url_for_go() -> str:
    """Return a lib/pq-compatible URL for the Go engine."""
    explicit = os.environ.get("MIGRATION_DATABASE_METADATA_URL", "").strip()
    if explicit:
        return explicit
    py_url = os.environ.get("METADATA_DB_URL", "").strip()
    if py_url.startswith("postgresql+asyncpg://"):
        return "postgresql://" + py_url.split("://", 1)[1]
    if py_url.startswith("postgresql://"):
        return py_url
    return "postgresql://postgres:postgres@localhost:5555/migration_checklist"


def _queue_path_for_go() -> str:
    raw = os.environ.get("MIGRATION_QUEUE_PATH", "data/migration_queue.bbolt").strip()
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    return str(path)


def _sync_go_engine_env() -> None:
    """Ensure Go engine env vars align with Python metadata settings."""
    os.environ.setdefault("MIGRATION_DATABASE_METADATA_URL", _metadata_url_for_go())
    queue = _queue_path_for_go()
    os.environ.setdefault("MIGRATION_QUEUE_PATH", queue)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    Path(queue).parent.mkdir(parents=True, exist_ok=True)


def _postgres_port_open(host: str = "127.0.0.1", port: int = 5555, timeout: float = 1.0) -> bool:
    import socket

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _using_postgres_metadata() -> bool:
    return "postgresql" in os.environ.get("METADATA_DB_URL", "")


def require_postgres_metadata() -> bool:
    """Ensure PostgreSQL metadata is reachable. Fails hard — no SQLite fallback."""
    load_env()
    if not _using_postgres_metadata():
        return True
    if _postgres_port_open():
        return True

    print(f" {C.RED}✗{C.END} Metadata PostgreSQL is not reachable on port 5555")
    print(f"   SQL Optima requires the {C.BOLD}postgres_checklist{C.END} database.")
    if IS_WINDOWS:
        print(f"   1. Install and start {C.CYAN}Docker Desktop{C.END}")
    else:
        print(f"   1. Install Docker and ensure the daemon is running")
    print(f"   2. From the project root, run:")
    print(f"      {C.CYAN}docker compose up postgres_checklist -d{C.END}")
    print(f"   3. Re-run: {C.BOLD}python start.py --all{C.END}")
    return False


# ── Setup ─────────────────────────────────────────────────────────────

def install_python_deps():
    if not _pip_available():
        ensure_project_venv()  # re-execs inside .venv when system Python lacks pip
    print(f"\n {C.BOLD}Installing Python dependencies...{C.END}")
    try:
        subprocess.check_call(
            [PYTHON, "-m", "pip", "install", "-e", ".[dev]"],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
        print(f" {C.GREEN}✓{C.END} Python dependencies installed")
    except subprocess.CalledProcessError:
        # Fallback to requirements.txt
        try:
            subprocess.check_call(
                [PYTHON, "-m", "pip", "install", "-r", "requirements.txt"],
                cwd=ROOT,
                stdout=subprocess.DEVNULL,
            )
            print(f" {C.GREEN}✓{C.END} Python dependencies installed (from requirements.txt)")
        except subprocess.CalledProcessError as e:
            print(f" {C.RED}✗{C.END} Failed to install Python deps: {e}")
            launcher = ".\\start.ps1 -setup" if IS_WINDOWS else "./start.sh --setup"
            print(f"   Try the platform launcher: {C.BOLD}{launcher}{C.END}")
            sys.exit(1)


def install_ui_deps():
    if not NPM:
        print(f" {C.YELLOW}⚠{C.END} Skipping UI deps (npm not found)")
        return False
    print(f"\n {C.BOLD}Installing UI dependencies...{C.END}")
    try:
        subprocess.check_call([NPM, "install", "--silent"], cwd=UI_DIR, stdout=subprocess.DEVNULL)
        print(f" {C.GREEN}✓{C.END} UI dependencies installed")
        return True
    except subprocess.CalledProcessError as e:
        print(f" {C.YELLOW}⚠{C.END} UI install failed: {e}")
        return False


def _go_engine_binary() -> Path:
    name = "migration-engine.exe" if IS_WINDOWS else "migration-engine"
    return ENGINE_DIR / name


def build_go_engine(*, quiet: bool = False) -> bool:
    """Compile the Go migration-engine binary (avoids slow silent ``go run`` at startup)."""
    if not shutil.which("go") or not ENGINE_DIR.is_dir():
        return False
    binary = _go_engine_binary()
    if not quiet:
        print(f"\n {C.BOLD}Building Go migration-engine...{C.END}")
        print(f" {C.DIM}  (first build downloads modules — may take 1–3 minutes){C.END}")
    try:
        subprocess.check_call(
            ["go", "build", "-o", str(binary), "./cmd/migration-engine"],
            cwd=ENGINE_DIR,
            stdout=subprocess.DEVNULL if quiet else None,
            stderr=subprocess.STDOUT if not quiet else subprocess.DEVNULL,
        )
        if not quiet:
            print(f" {C.GREEN}✓{C.END} Go engine built ({binary.name})")
        return True
    except subprocess.CalledProcessError:
        if not quiet:
            print(f" {C.YELLOW}⚠{C.END} Go build failed — will retry with ``go run`` at engine start")
        return False


def _engine_startup_complete(pid: int) -> bool:
    """True when the engine process logged a successful startup line."""
    for line in _subprocess_log_buffers.get(pid, []):
        low = line.lower()
        if "migration worker loop started" in low or "migration engine starting" in low:
            return True
    return False


# ── Docker services ───────────────────────────────────────────────────

def _docker_available() -> bool:
    try:
        subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def ensure_postgres_checklist() -> bool:
    """Start the postgres_checklist container if it isn't already running.

    Returns True when the container is healthy, False if Docker is unavailable
    or startup fails (caller may still proceed — app will error on connect).
    """
    print(f"\n {C.BOLD}Checking metadata database (postgres_checklist)...{C.END}")

    if not _docker_available():
        print(f" {C.YELLOW}⚠{C.END} Docker not available — skipping postgres_checklist auto-start")
        if IS_WINDOWS:
            print(f"   Install {C.CYAN}Docker Desktop{C.END} and ensure it is running, then retry.")
            print(f"   Or start metadata DB manually: docker compose up postgres_checklist -d")
        return False

    # Check if already running and healthy
    try:
        out = subprocess.check_output(
            ["docker", "inspect", "--format", "{{.State.Health.Status}}", "postgres_checklist"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
        if out == "healthy":
            print(f" {C.GREEN}✓{C.END} postgres_checklist already running")
            return True
        if out in ("starting", "unhealthy", "none"):
            pass  # fall through to start/wait
    except subprocess.CalledProcessError:
        pass  # container doesn't exist yet

    # Start (or restart) via docker-compose
    print(f" {C.CYAN}→{C.END} Starting postgres_checklist container...")
    try:
        subprocess.check_call(
            ["docker", "compose", "up", "postgres_checklist", "-d", "--wait"],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError:
        # Fallback: older docker-compose v1
        try:
            subprocess.check_call(
                ["docker-compose", "up", "postgres_checklist", "-d"],
                cwd=ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
            )
        except subprocess.CalledProcessError as e:
            print(f" {C.RED}✗{C.END} Failed to start postgres_checklist: {e}")
            return False

    # Wait up to 30 s for pg_isready on port 5555
    import socket
    for attempt in range(30):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            result = s.connect_ex(("127.0.0.1", 5555))
            s.close()
            if result == 0:
                print(f" {C.GREEN}✓{C.END} postgres_checklist is ready on port 5555")
                return True
        except OSError:
            pass
        time.sleep(1)

    print(f" {C.YELLOW}⚠{C.END} postgres_checklist did not become ready within 30s — proceeding anyway")
    return False


def cleanup_stale_sqlite() -> None:
    """Remove legacy SQLite metadata DB when PostgreSQL is configured.

    A leftover migration_platform.db causes confusion when METADATA_DB_URL points
    at postgres_checklist but an old zero-config SQLite file still exists.
    """
    load_env()
    url = os.environ.get("METADATA_DB_URL", "")
    if "postgresql" not in url:
        return
    stale = ROOT / "migration_platform.db"
    if stale.exists():
        stale.unlink()
        print(f" {C.YELLOW}✦{C.END} Removed stale {stale.name} (using PostgreSQL metadata store)")


def run_metadata_migrations() -> bool:
    """Bootstrap the metadata schema before the API starts."""
    load_env()
    url = os.environ.get("METADATA_DB_URL", "")
    if "postgresql" not in url:
        return True

    print(f"\n {C.BOLD}Applying metadata database migrations...{C.END}")
    try:
        import asyncio

        from infrastructure.metadata_db.session import init_db

        asyncio.run(init_db())
        print(f" {C.GREEN}✓{C.END} Metadata schema is ready")
        return True
    except Exception as e:
        print(f" {C.RED}✗{C.END} Metadata database setup failed: {e}")
        print(f"   Ensure postgres_checklist is running and METADATA_DB_URL is correct.")
        err = str(e).lower()
        if "migration_job_id" in err or "undefinedcolumn" in err:
            print(f"   Stale metadata schema detected. Reset the checklist database volume:")
            print(f"   {C.CYAN}docker compose down postgres_checklist{C.END}")
            print(f"   {C.CYAN}docker volume rm sqloptima_migration_pg_checklist_data{C.END}")
            print(f"   (volume name may differ — run {C.CYAN}docker volume ls{C.END} and remove *pg_checklist*)")
        else:
            print(f"   Fresh reset: docker compose down postgres_checklist && docker volume rm <pg_checklist_volume>")
        return False


# ── Servers ───────────────────────────────────────────────────────────

processes: list[subprocess.Popen] = []
_subprocess_log_buffers: dict[int, list[str]] = {}
_docker_engine_started_by_us = False


def _unregister_process(proc: subprocess.Popen | None) -> None:
    """Drop a subprocess from the monitor list (e.g. after a failed startup)."""
    if proc is None:
        return
    try:
        processes.remove(proc)
    except ValueError:
        pass


def _drain_subprocess_output(proc: subprocess.Popen, *, max_lines: int = 40) -> list[str]:
    """Read any buffered stdout from a subprocess that already exited."""
    if not proc.stdout:
        return []
    lines: list[str] = []
    while len(lines) < max_lines:
        line = proc.stdout.readline()
        if not line:
            break
        lines.append(line.rstrip())
    return lines


def _print_subprocess_failure(name: str, proc: subprocess.Popen, *, hints: list[str] | None = None) -> None:
    """Surface the last lines of a failed child process to aid troubleshooting."""
    print(f" {C.RED}✗{C.END} {name} exited (code {proc.returncode})")
    tail = _subprocess_log_buffers.get(proc.pid, []) or _drain_subprocess_output(proc)
    if tail:
        print(f" {C.DIM}  Last output:{C.END}")
        # Prefer full traceback block when present.
        start = 0
        for i, line in enumerate(tail):
            if "traceback" in line.lower():
                start = i
        for line in tail[start:][-25:]:
            print(f"    {line}")
    if hints:
        print(f" {C.YELLOW}  Hints:{C.END}")
        for hint in hints:
            print(f"    • {hint}")


def _should_print_service_log(line: str) -> bool:
    """Return True only for real warnings/errors from subprocess stdout.

    Avoid printing INFO structlog lines that merely contain field names like
    ``warning=11`` or ``overall_tier=WARNING`` (assessment counters).
    """
    low = line.lower()
    if "[info" in low or "[debug" in low:
        return False
    if "[warning" in low or "[error" in low or "[critical" in low:
        return True
    if any(k in low for k in ("traceback", "exception (", " critical:")):
        return True
    if any(
        k in low
        for k in (
            "error:",
            "runtimeerror",
            "importerror",
            "modulenotfounderror",
            "connectionrefused",
            "cannot connect",
            'file "',
            "  file ",
            "raise ",
        )
    ):
        return True
    if " failed" in low or low.startswith("failed"):
        return True
    return False


def _should_print_ui_log(line: str) -> bool:
    """Next.js dev server — surface compile warnings and errors."""
    low = line.lower()
    return any(
        k in low
        for k in ("error", "warn", "critical", "exception", "traceback", "failed")
    )


def _api_subprocess_env() -> dict[str, str]:
    """Child env for the API: quiet console logs unless explicitly configured."""
    load_env()
    env = os.environ.copy()
    env.setdefault("MIGRATION_LOG_LEVEL", "WARNING")
    if IS_WINDOWS:
        env.setdefault("PYTHONUTF8", "1")

    # Sync DB URLs: if one is set, set the other to ensure consistency between Python/Go parts.
    m_url = env.get("MIGRATION_DATABASE_METADATA_URL")
    p_url = env.get("METADATA_DB_URL")
    if m_url and not p_url:
        env["METADATA_DB_URL"] = m_url
    elif p_url and not m_url:
        env["MIGRATION_DATABASE_METADATA_URL"] = p_url

    return env


def _win_app_control_blocked(exc: BaseException) -> bool:
    """True when Windows Application Control / Smart App Control blocks execution."""
    if not IS_WINDOWS:
        return False
    if isinstance(exc, OSError) and getattr(exc, "winerror", None) == 4551:
        return True
    return "4551" in str(exc) and "application control" in str(exc).lower()


def _api_failure_hints(log_tail: list[str] | None = None) -> list[str]:
    hints = [
        "Install deps: python start.py --setup  or  .\\start.ps1 -setup",
        "Start metadata DB: docker compose up postgres_checklist -d",
        "Ensure Docker Desktop is running (Windows)",
    ]
    joined = "\n".join(log_tail or []).lower()
    if "unicodedecodeerror" in joined and ".env" in joined:
        hints.insert(
            0,
            "Delete .env and re-run, or: python start.py --clean --all (repairs UTF-8 encoding)",
        )
    if IS_WINDOWS:
        hints.append(
            "Full logs: .\\.venv\\Scripts\\python.exe -m uvicorn apps.api.main:app --port 8508",
        )
    else:
        hints.append("Full logs: .venv/bin/python -m uvicorn apps.api.main:app --port 8508")
    return hints


def _go_engine_blocked_hints() -> list[str]:
    return [
        "Windows Application Control blocked the local Go binary",
        "Ask IT to allowlist engine-go\\migration-engine.exe, or use Docker:",
        "  docker compose up postgres_checklist migration-engine -d",
        "Or run API/UI only: python start.py --api --ui (no bulk data migration)",
        "Install Go 1.23+ and ensure `go version` works in this terminal",
    ]


def start_go_engine_docker(env: dict[str, str]) -> bool:
    """Start migration-engine in Docker when the local binary is blocked on Windows."""
    global _docker_engine_started_by_us
    if not _docker_available():
        return False
    print(f"\n {C.CYAN}→{C.END} Starting Go migration-engine via Docker...")
    compose_env = os.environ.copy()
    master_key = env.get("MIGRATION_MASTER_KEY", "").strip()
    if master_key:
        compose_env["MIGRATION_MASTER_KEY"] = master_key
    for cmd in (
        ["docker", "compose", "up", "migration-engine", "-d", "--build"],
        ["docker-compose", "up", "migration-engine", "-d", "--build"],
    ):
        try:
            subprocess.check_call(cmd, cwd=ROOT, env=compose_env)
            _docker_engine_started_by_us = True
            print(f" {C.GREEN}✓{C.END} Go migration-engine running in Docker")
            print("   metadata: postgresql://postgres:postgres@localhost:5555/migration_checklist")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    print(f" {C.YELLOW}⚠{C.END} Could not start migration-engine container")
    return False


def _launch_go_engine_subprocess(
    engine_cmd: list[str],
    *,
    engine_cwd: Path,
    env: dict[str, str],
) -> subprocess.Popen:
    return subprocess.Popen(
        engine_cmd,
        cwd=engine_cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        bufsize=1,
        env=env,
    )


def _wait_for_go_engine(proc: subprocess.Popen, env: dict[str, str]) -> bool:
    """Stream engine logs and wait until startup completes or the process exits."""
    import threading

    def stream_output() -> None:
        if not proc.stdout:
            return
        buf = _subprocess_log_buffers.setdefault(proc.pid, [])
        for line in iter(proc.stdout.readline, ""):
            if not line:
                break
            l = line.rstrip()
            buf.append(l)
            low = l.lower()
            if any(
                k in low
                for k in ("error", "fatal", "panic", "connect metadata", "migration engine", "migration worker")
            ):
                print(f"  [engine] {l}")

    threading.Thread(target=stream_output, daemon=True).start()

    deadline = time.time() + 180
    last_progress = time.time()
    while time.time() < deadline:
        if proc.poll() is not None:
            _unregister_process(proc)
            _print_subprocess_failure(
                "migration-engine",
                proc,
                hints=[
                    "Install Go 1.23+ and ensure `go version` works in this terminal",
                    "Start Docker Desktop, then run: docker compose up postgres_checklist -d",
                    f"Verify metadata DB: {env['MIGRATION_DATABASE_METADATA_URL']}",
                    "Run engine alone for full logs: python start.py --engine",
                ],
            )
            return False
        if _engine_startup_complete(proc.pid):
            return True
        if time.time() - last_progress >= 15:
            print(f"  {C.DIM}… still starting (waiting for engine logs){C.END}")
            last_progress = time.time()
        time.sleep(0.5)
    return True


def prepare_windows_startup() -> None:
    """Windows-first startup: UTF-8 .env, then metadata DB before API/engine."""
    if not IS_WINDOWS:
        return
    ensure_env()
    load_env()
    print(f"\n {C.BOLD}Windows startup preparation{C.END}")
    print(f" {C.GREEN}✓{C.END} .env validated (UTF-8)")
    if not _docker_available():
        print(f" {C.YELLOW}⚠{C.END} Docker Desktop not detected — metadata DB must be started manually")
        print(f"   Run: {C.CYAN}docker compose up postgres_checklist -d{C.END}")
    else:
        print(f" {C.GREEN}✓{C.END} Docker available — metadata DB will be started next")


def start_go_engine() -> subprocess.Popen | None:
    """Start the Go migration-engine worker."""
    if not shutil.which("go"):
        print(f" {C.YELLOW}⚠{C.END} Go toolchain not found — skipping migration-engine")
        return None
    if not ENGINE_DIR.is_dir():
        print(f" {C.RED}✗{C.END} engine-go/ not found — skipping migration-engine")
        return None

    load_env()
    if not _using_postgres_metadata() or not _postgres_port_open():
        print(f" {C.YELLOW}⚠{C.END} Go migration-engine requires PostgreSQL metadata (port 5555)")
        print(f"   Start Docker Desktop, then: {C.CYAN}docker compose up postgres_checklist -d{C.END}")
        return None

    _sync_go_engine_env()

    binary = _go_engine_binary()
    if not binary.is_file():
        print(f"\n {C.CYAN}→{C.END} Go binary missing — compiling now...")
        build_go_engine()

    print(f"\n {C.BOLD}Starting Go migration-engine...{C.END}")
    env = os.environ.copy()
    env["MIGRATION_DATABASE_METADATA_URL"] = _metadata_url_for_go()
    env["MIGRATION_QUEUE_PATH"] = _queue_path_for_go()
    if not env.get("MIGRATION_MASTER_KEY"):
        print(f" {C.YELLOW}⚠{C.END} MIGRATION_MASTER_KEY not set — password decryption will fail")

    # Engine cwd must be engine-go/ — config lives at engine-go/config/default.toml
    engine_cwd = ENGINE_DIR
    engine_cmds: list[list[str]] = []
    if binary.is_file():
        engine_cmds.append([str(binary.resolve())])
    engine_cmds.append(["go", "run", "./cmd/migration-engine"])

    app_control_blocked = False
    for idx, engine_cmd in enumerate(engine_cmds):
        if idx > 0:
            label = "go run" if engine_cmd[0] == "go" else engine_cmd[0]
            print(f" {C.CYAN}→{C.END} Retrying migration-engine with {label}...")
            if engine_cmd[0] == "go":
                print(f" {C.DIM}  (first compile may take 1-3 min){C.END}")
        try:
            proc = _launch_go_engine_subprocess(engine_cmd, engine_cwd=engine_cwd, env=env)
        except OSError as exc:
            if _win_app_control_blocked(exc):
                app_control_blocked = True
                print(f" {C.YELLOW}⚠{C.END} Windows blocked {engine_cmd[0]} (Application Control policy)")
                continue
            print(f" {C.RED}✗{C.END} Failed to start migration-engine: {exc}")
            return None

        processes.append(proc)
        if _wait_for_go_engine(proc, env):
            print(f" {C.GREEN}✓{C.END} Go migration-engine started")
            print(f"   metadata: {env['MIGRATION_DATABASE_METADATA_URL']}")
            print(f"   queue:    {env['MIGRATION_QUEUE_PATH']}")
            return proc

    if IS_WINDOWS and start_go_engine_docker(env):
        return None

    if app_control_blocked:
        print(f" {C.RED}✗{C.END} Failed to start migration-engine (Windows Application Control)")
        print(f" {C.YELLOW}  Hints:{C.END}")
        for hint in _go_engine_blocked_hints():
            print(f"    • {hint}")
    return None


def start_api() -> subprocess.Popen | None:
    """Start the FastAPI server and stream its output to console."""
    print(f"\n {C.BOLD}Starting API server...{C.END}")
    try:
        api_cmd = [
            PYTHON, "-m", "uvicorn", "apps.api.main:app",
            "--host", "0.0.0.0", "--port", "8508",
            "--log-level", "warning",
        ]
        # uvicorn --reload uses multiprocessing spawn; it is unreliable on Windows.
        if not IS_WINDOWS:
            api_cmd.append("--reload")
        proc = subprocess.Popen(
            api_cmd,
            cwd=ROOT,
            env=_api_subprocess_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding='utf-8',
            bufsize=1,
        )
        processes.append(proc)

        import threading

        def stream_output():
            if not proc or not proc.stdout:
                return
            buf = _subprocess_log_buffers.setdefault(proc.pid, [])
            for line in iter(proc.stdout.readline, ""):
                if not line:
                    break
                l = line.rstrip()
                buf.append(l)
                if _should_print_service_log(l):
                    print(f"  {l}")

        t = threading.Thread(target=stream_output, daemon=True)
        t.start()

        # Wait for startup via health endpoint
        import urllib.request
        for _ in range(60):
            if proc.poll() is not None:
                _unregister_process(proc)
                tail = _subprocess_log_buffers.get(proc.pid, [])
                _print_subprocess_failure(
                    "API server",
                    proc,
                    hints=_api_failure_hints(tail),
                )
                return None
            try:
                resp = urllib.request.urlopen("http://localhost:8508/health", timeout=1)
                if resp.status == 200:
                    print(f" {C.GREEN}✓{C.END} API running at {C.BOLD}http://localhost:8508{C.END}")
                    return proc
            except Exception:
                pass
            time.sleep(0.5)
        if proc.poll() is not None:
            _unregister_process(proc)
            _print_subprocess_failure("API server", proc)
            return None
        print(f" {C.YELLOW}⚠{C.END} API started (may still be loading)")
        return proc
    except Exception as e:
        print(f" {C.RED}✗{C.END} Failed to start API: {e}")
        return None


def start_ui() -> subprocess.Popen | None:
    """Start the Next.js dev server and stream its output to console."""
    if not NPM:
        return None
    print(f"\n {C.BOLD}Starting UI dev server...{C.END}")
    try:
        proc = subprocess.Popen(
            [NPM, "run", "dev"],
            cwd=UI_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding='utf-8',
            bufsize=1,
        )
        processes.append(proc)

        import threading

        def stream_output():
            if not proc or not proc.stdout:
                return
            for line in iter(proc.stdout.readline, ""):
                if not line:
                    break
                l = line.rstrip()
                if _should_print_ui_log(l):
                    print(f"  {l}")

        t = threading.Thread(target=stream_output, daemon=True)
        t.start()

        # Wait for it to bind
        for _ in range(30):
            if proc.poll() is not None:
                break
            try:
                import socket
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                result = s.connect_ex(("127.0.0.1", 3508))
                s.close()
                if result == 0:
                    print(f" {C.GREEN}✓{C.END} UI running at {C.BOLD}http://localhost:3508{C.END}")
                    return proc
            except Exception:
                pass
            time.sleep(0.5)
        if proc.poll() is None:
            print(f" {C.GREEN}✓{C.END} UI running at {C.BOLD}http://localhost:3508{C.END}")
        return proc
    except Exception as e:
        print(f" {C.RED}✗{C.END} Failed to start UI: {e}")
        return None


def _kill_proc_tree(proc: subprocess.Popen) -> None:
    """Kill a process and all its children (cross-platform)."""
    if IS_WINDOWS:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    else:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def shutdown(signum=None, frame=None):
    global _docker_engine_started_by_us
    print(f"\n\n {C.YELLOW}Shutting down...{C.END}")
    for proc in processes:
        if proc and proc.poll() is None:
            _kill_proc_tree(proc)
    if _docker_engine_started_by_us:
        for cmd in (
            ["docker", "compose", "stop", "migration-engine"],
            ["docker-compose", "stop", "migration-engine"],
        ):
            try:
                subprocess.run(cmd, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                print(f" {C.GREEN}✓{C.END} Stopped Docker migration-engine")
                break
            except (subprocess.CalledProcessError, FileNotFoundError):
                continue
        _docker_engine_started_by_us = False
    print(f" {C.GREEN}✓{C.END} All services stopped")
    sys.exit(0)


# ── Fresh install ───────────────────────────────────────────────────────

def _remove_path(path: Path, label: str) -> None:
    if not path.exists():
        return
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        print(f" {C.GREEN}✓{C.END} Removed {label}")
    except OSError as exc:
        print(f" {C.YELLOW}⚠{C.END} Could not remove {label}: {exc}")


def _clean_docker_metadata() -> None:
    print(f"\n {C.BOLD}Resetting Docker metadata database...{C.END}")
    if not _docker_available():
        print(f" {C.YELLOW}⚠{C.END} Docker not running — skipped container/volume reset")
        return
    for cmd in (
        ["docker", "compose", "down", "postgres_checklist", "-v"],
        ["docker-compose", "down", "postgres_checklist", "-v"],
    ):
        try:
            subprocess.run(
                cmd, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True,
            )
            print(f" {C.GREEN}✓{C.END} postgres_checklist container and volume removed")
            return
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    print(f" {C.YELLOW}⚠{C.END} Could not reset postgres_checklist (run manually: docker compose down postgres_checklist -v)")


def clean_fresh_install(*, purge_deps: bool = False) -> None:
    """Remove local state so the next start mimics a first-time install."""
    print(f"\n {C.BOLD}{'='*50}{C.END}")
    print(f" {C.BOLD}  Fresh install — cleaning local state{C.END}")
    print(f" {C.BOLD}{'='*50}{C.END}")

    _clean_docker_metadata()

    print(f"\n {C.BOLD}Removing local files...{C.END}")
    _remove_path(ENV_FILE, ".env (new keys will be generated)")
    _remove_path(ROOT / "migration_platform.db", "migration_platform.db")
    _remove_path(ROOT / "migration_jobs.json", "migration_jobs.json")
    _remove_path(DATA_DIR, "data/ (Go queue, etc.)")
    _remove_path(_go_engine_binary(), f"engine-go/{_go_engine_binary().name}")
    _remove_path(UI_DIR / ".next", "apps/ui/.next (Next.js cache)")

    if purge_deps:
        print(f"\n {C.BOLD}Removing installed dependencies...{C.END}")
        _remove_path(VENV_DIR, ".venv")
        _remove_path(UI_DIR / "node_modules", "apps/ui/node_modules")

    print(f"\n {C.GREEN}✓{C.END} Clean complete — next start is a fresh install.")


# ── Tests ─────────────────────────────────────────────────────────────

def run_tests():
    print(f"\n {C.BOLD}Running tests...{C.END}")
    result = subprocess.run(
        [PYTHON, "-m", "pytest", "tests/", "-q", "--tb=short"],
        cwd=ROOT,
    )
    if result.returncode == 0:
        print(f"\n {C.GREEN}✓{C.END} All tests passed")
    else:
        print(f"\n {C.RED}✗{C.END} Some tests failed (exit code {result.returncode})")
    return result.returncode


# ── Main ──────────────────────────────────────────────────────────────

def setup():
    print(f"\n {C.BOLD}{'='*50}{C.END}")
    print(f" {C.BOLD}  Prerequisites Check{C.END}")
    print(f" {C.BOLD}{'='*50}{C.END}")
    ok = check_python()
    has_node = check_node()
    has_go = check_go()
    if not ok:
        sys.exit(1)

    ensure_env()
    load_env()

    print(f"\n {C.BOLD}{'='*50}{C.END}")
    print(f" {C.BOLD}  Installing Dependencies{C.END}")
    print(f" {C.BOLD}{'='*50}{C.END}")
    install_python_deps()
    ui_ok = install_ui_deps()
    if has_go:
        build_go_engine()

    return has_node and ui_ok


def main():
    parser = argparse.ArgumentParser(
        description="Migration Platform — one-command launcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python start.py              Interactive menu
  python start.py --all        Start API + UI + Go engine (recommended)
  python start.py --clean --all   Fresh install + start everything
  python start.py --engine     Start Go migration-engine only
  python start.py --api          Start API only
  python start.py --ui           Start UI only
  python start.py --setup        Install dependencies only
  python start.py --test         Run the test suite
  python start.py 1              Start all (no prompt)
        """,
    )
    parser.add_argument("--all", action="store_true", help="Start API + UI + Go engine")
    parser.add_argument("--api", action="store_true", help="Start API server only")
    parser.add_argument("--ui", action="store_true", help="Start UI dev server only")
    parser.add_argument("--engine", action="store_true", help="Start Go migration-engine only")
    parser.add_argument("--setup", action="store_true", help="Install dependencies only")
    parser.add_argument("--test", action="store_true", help="Run tests")
    parser.add_argument("--clean", action="store_true",
                        help="Reset metadata DB, .env, and local data (fresh install)")
    parser.add_argument("--purge-deps", action="store_true",
                        help="With --clean: also remove .venv and node_modules")
    parser.add_argument("--no-ui", action="store_true", help="Skip UI setup/start")
    parser.add_argument("option", nargs="?", type=int, choices=[1, 2, 3, 4, 5],
                        help="Menu option: 1=all, 2=API, 3=UI, 4=tests, 5=exit")

    args = parser.parse_args()

    if args.clean:
        clean_fresh_install(purge_deps=args.purge_deps)
        if not (args.all or args.api or args.ui or args.engine or args.setup or args.test):
            print(f"\n {C.CYAN}→{C.END} Run {C.BOLD}python start.py --all{C.END} to start fresh.")
            return

    _load_bootstrap_path()
    _refresh_tool_paths()
    ensure_project_venv()

    print_banner()

    # ── Setup-only ──
    if args.setup:
        setup()
        print(f"\n {C.GREEN}✓{C.END} Setup complete. Run {C.BOLD}python start.py{C.END} to start.")
        return

    # ── Tests ──
    if args.test:
        setup()
        sys.exit(run_tests())

    # ── Interactive menu ──
    ui_ok = setup()

    if not args.api and not args.ui and not args.all and not args.engine:
        if args.option is not None:
            choice = str(args.option)
        else:
            print(f"\n {C.BOLD}{'='*50}{C.END}")
            print(f" {C.BOLD}  What would you like to do?{C.END}")
            print(f" {C.BOLD}{'='*50}{C.END}")
            print(f"  {C.CYAN}1{C.END})  Start everything (API + UI + Go engine)")
            print(f"  {C.CYAN}2{C.END})  Start API server only")
            if ui_ok:
                print(f"  {C.CYAN}3{C.END})  Start UI dev server only")
            print(f"  {C.CYAN}4{C.END})  Run tests")
            print(f"  {C.CYAN}5{C.END})  Exit")
            print()
            try:
                choice = input(f"  {C.BOLD}Choice [1]{C.END}: ").strip() or "1"
            except (EOFError, KeyboardInterrupt):
                print()
                return

        if choice == "2":
            args.api = True
        elif choice == "3" and ui_ok:
            args.ui = True
        elif choice == "4":
            sys.exit(run_tests())
        elif choice == "5":
            return
        else:
            args.all = True

    # ── Start services ──
    prepare_windows_startup()
    load_env()
    import signal
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    started = False

    if args.all or args.api or args.engine:
        ensure_postgres_checklist()
        if not require_postgres_metadata():
            sys.exit(1)

    if args.all or args.api:
        cleanup_stale_sqlite()
        if not run_metadata_migrations():
            sys.exit(1)
        api_proc = start_api()
        if api_proc:
            started = True

    engine_running = False
    if args.engine or args.all:
        engine_proc = start_go_engine()
        if engine_proc or _docker_engine_started_by_us:
            started = True
            engine_running = True
        elif args.engine:
            print(f"\n {C.RED}Go engine failed to start.{C.END}")
            return
        elif args.all:
            print(f" {C.YELLOW}⚠{C.END} Continuing without Go engine — data migrations will not run")

    if args.all or args.ui:
        ui_proc = start_ui()
        if ui_proc:
            started = True

    if not started:
        print(f"\n {C.YELLOW}No services started.{C.END}")
        return

    # Detect local network IP for sharing across the network
    local_ip = "localhost"
    try:
        import socket as _sock
        with _sock.socket(_sock.AF_INET, _sock.SOCK_DGRAM) as _s:
            _s.connect(("8.8.8.8", 80))
            local_ip = _s.getsockname()[0]
    except Exception:
        pass

    print(f"\n {C.BOLD}{'='*55}{C.END}")
    print(f" {C.GREEN}  SQL Optima Migration is running!{C.END}")
    print(f" {C.BOLD}{'='*55}{C.END}")
    if args.api or args.all:
        print(f"   API  (local):   {C.CYAN}http://localhost:8508{C.END}")
        print(f"   API  (network): {C.CYAN}http://{local_ip}:8508{C.END}")
        print(f"   Docs:           {C.CYAN}http://localhost:8508/docs{C.END}")
    if args.engine or args.all:
        if engine_running:
            print(f"   Engine:         {C.GREEN}Go migration-engine running{C.END}")
        else:
            print(f"   Engine:         {C.YELLOW}not running (see errors above){C.END}")
    if (args.ui or args.all) and ui_ok:
        print(f"   UI   (local):   {C.CYAN}http://localhost:3508{C.END}")
        print(f"   UI   (network): {C.CYAN}http://{local_ip}:3508{C.END}")
    print(f"\n   Press {C.BOLD}Ctrl+C{C.END} to stop all services")

    # Open the dashboard in the default browser once the UI is ready
    if (args.ui or args.all) and ui_ok:
        import webbrowser
        dashboard_url = "http://localhost:3508"
        print(f"\n {C.CYAN}→{C.END} Opening dashboard in your browser...")
        webbrowser.open(dashboard_url)

    try:
        while True:
            time.sleep(1)
            # Check if any process died
            for i, proc in enumerate(processes):
                if proc and proc.poll() is not None:
                    print(f" {C.YELLOW}⚠{C.END} A process exited unexpectedly (code {proc.returncode})")
                    shutdown()
    except KeyboardInterrupt:
        shutdown()


if __name__ == "__main__":
    main()
