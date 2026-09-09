#!/usr/bin/env bash
# SQL Optima — Docker-only installer. No Python, Node, or Go on the host.
# Usage:
#   ./sql-optima.sh              # start (or install into ~/sql-optima)
#   ./sql-optima.sh stop
#   ./sql-optima.sh status
set -euo pipefail

VERSION="${SQLOPTIMA_VERSION:-0.2.0}"
REGISTRY="${SQLOPTIMA_IMAGE_REGISTRY:-ghcr.io/rsharma155}"
UI_URL="http://localhost:3508"
API_HEALTH="http://localhost:8508/health"

resolve_root() {
  if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
    cd "$(dirname "${BASH_SOURCE[0]}")"
    pwd
  else
    local home="${SQLOPTIMA_HOME:-${HOME}/sql-optima}"
    mkdir -p "$home"
    printf '%s\n' "$home"
  fi
}

ROOT="$(resolve_root)"
cd "$ROOT"

write_compose() {
  if [[ -f docker-compose.yml ]]; then
    return
  fi
  cat > docker-compose.yml <<'YAML'
name: sqloptima

services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: migration_checklist
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: ${METADATA_DB_PASSWORD:?Set METADATA_DB_PASSWORD in .env}
    volumes:
      - sqloptima_pg:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d migration_checklist"]
      interval: 5s
      timeout: 5s
      retries: 10
      start_period: 10s
    restart: unless-stopped

  api:
    image: ${SQLOPTIMA_IMAGE_REGISTRY:-ghcr.io/rsharma155}/sqloptima-api:${SQLOPTIMA_VERSION:-0.2.0}
    ports:
      - "8508:8508"
    environment:
      METADATA_DB_HOST: postgres
      METADATA_DB_PORT: "5432"
      METADATA_DB_URL: postgresql+asyncpg://postgres:${METADATA_DB_PASSWORD}@postgres:5432/migration_checklist
      MIGRATION_DATABASE_METADATA_URL: postgresql://postgres:${METADATA_DB_PASSWORD}@postgres:5432/migration_checklist
      MIGRATION_MASTER_KEY: ${MIGRATION_MASTER_KEY:?Set MIGRATION_MASTER_KEY in .env}
      MIGRATION_JWT_SECRET: ${MIGRATION_JWT_SECRET:?Set MIGRATION_JWT_SECRET in .env}
      MIGRATION_EDITION: ${MIGRATION_EDITION:-enterprise}
      MIGRATION_LICENSE_KEY: ${MIGRATION_LICENSE_KEY:-DEV-LOCAL}
      MIGRATION_ENV: ${MIGRATION_ENV:-on-prem}
      MIGRATION_DEPLOYMENT: on-prem
      ENVIRONMENT: ${ENVIRONMENT:-development}
      MIGRATION_ALLOWED_ORIGINS: ${MIGRATION_ALLOWED_ORIGINS:-}
    depends_on:
      postgres:
        condition: service_healthy
    healthcheck:
      test:
        [
          "CMD",
          "python",
          "-c",
          "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8508/health', timeout=5)",
        ]
      interval: 10s
      timeout: 5s
      retries: 12
      start_period: 40s
    restart: unless-stopped

  ui:
    image: ${SQLOPTIMA_IMAGE_REGISTRY:-ghcr.io/rsharma155}/sqloptima-ui:${SQLOPTIMA_VERSION:-0.2.0}
    ports:
      - "3508:3508"
    environment:
      NEXT_PUBLIC_API_URL: http://localhost:8508
    depends_on:
      api:
        condition: service_healthy
    restart: unless-stopped

  migration-engine:
    image: ${SQLOPTIMA_IMAGE_REGISTRY:-ghcr.io/rsharma155}/sqloptima-engine:${SQLOPTIMA_VERSION:-0.2.0}
    environment:
      MIGRATION_MASTER_KEY: ${MIGRATION_MASTER_KEY}
      MIGRATION_DATABASE_METADATA_URL: postgresql://postgres:${METADATA_DB_PASSWORD}@postgres:5432/migration_checklist
      MIGRATION_QUEUE_PATH: /var/lib/sqloptima/migration_queue.bbolt
      MIGRATION_LOGGING_FORMAT: text
    volumes:
      - sqloptima_queue:/var/lib/sqloptima
    depends_on:
      postgres:
        condition: service_healthy
      api:
        condition: service_healthy
    restart: unless-stopped

volumes:
  sqloptima_pg:
  sqloptima_queue:
YAML
}

b64_key() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 32 | tr -d '\n'
  else
    tr -dc 'A-Za-z0-9' </dev/urandom | head -c 40
  fi
}

alnum_password() {
  tr -dc 'A-Za-z0-9' </dev/urandom | head -c 24
}

ensure_env() {
  if [[ -f .env ]]; then
    return
  fi
  cat > .env <<EOF
SQLOPTIMA_VERSION=${VERSION}
SQLOPTIMA_IMAGE_REGISTRY=${REGISTRY}
MIGRATION_MASTER_KEY=$(b64_key)
MIGRATION_JWT_SECRET=$(b64_key)
METADATA_DB_PASSWORD=$(alnum_password)
MIGRATION_EDITION=enterprise
MIGRATION_LICENSE_KEY=DEV-LOCAL
MIGRATION_ENV=on-prem
ENVIRONMENT=development
EOF
  echo "Created $ROOT/.env with generated secrets. Keep this file private."
}

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
  else
    echo "Docker Compose is not available. Install Docker Desktop or Docker Engine, then retry." >&2
    echo "https://docs.docker.com/get-docker/" >&2
    exit 1
  fi
}

require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is required and is the only tool you need to install." >&2
    echo "Install Docker Desktop (Windows/macOS) or Docker Engine (Linux):" >&2
    echo "  https://docs.docker.com/get-docker/" >&2
    exit 1
  fi
  if ! docker info >/dev/null 2>&1; then
    echo "Docker is installed but not running. Start Docker Desktop / the Docker service, then retry." >&2
    exit 1
  fi
}

wait_healthy() {
  local i
  for i in $(seq 1 90); do
    if curl -fsS "$API_HEALTH" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "SQL Optima started but the API is not healthy yet. Check: docker compose -f \"$ROOT/docker-compose.yml\" logs" >&2
  return 1
}

open_browser() {
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$UI_URL" >/dev/null 2>&1 || true
  elif command -v open >/dev/null 2>&1; then
    open "$UI_URL" || true
  fi
}

cmd="${1:-start}"

require_docker
write_compose
ensure_env

case "$cmd" in
  stop)
    compose down
    echo "SQL Optima stopped. Data is kept in Docker volumes."
    ;;
  status)
    compose ps
    ;;
  start|up|"")
    echo "Pulling SQL Optima images (no compile on this machine)..."
    compose pull
    compose up -d
    echo "Waiting for the app..."
    wait_healthy || true
    echo
    echo "SQL Optima is running."
    echo "  Dashboard: $UI_URL"
    echo "  API:        http://localhost:8508"
    echo "Open the dashboard and create the first admin account."
    open_browser
    ;;
  *)
    echo "Usage: $0 [start|stop|status]" >&2
    exit 1
    ;;
esac
