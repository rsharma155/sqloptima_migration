#!/usr/bin/env bash
# SQL Optima Migration — Docker-only installer. No Python, Node, or Go on the host.
# Usage:
#   ./sql-optima.sh              # start (or install into ~/sql-optima)
#   ./sql-optima.sh stop
#   ./sql-optima.sh status
set -euo pipefail

VERSION="${SQLOPTIMA_VERSION:-0.2.1}"
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
  cat > docker-compose.yml <<'YAML'
name: sqloptima_migration

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
    image: ${SQLOPTIMA_IMAGE_REGISTRY:-ghcr.io/rsharma155}/sqloptima_migration-api:${SQLOPTIMA_VERSION:-0.2.1}
    ports:
      - "${SQLOPTIMA_API_PORT:-8508}:8508"
    env_file:
      - .env
    environment:
      METADATA_DB_HOST: postgres
      METADATA_DB_PORT: "5432"
      METADATA_DB_USER: postgres
      METADATA_DB_NAME: migration_checklist
      METADATA_DB_PASSWORD: ${METADATA_DB_PASSWORD:?Set METADATA_DB_PASSWORD in .env}
      METADATA_DB_URL: "postgresql+asyncpg://postgres:${METADATA_DB_PASSWORD}@postgres:5432/migration_checklist"
      MIGRATION_DATABASE_METADATA_URL: "postgresql://postgres:${METADATA_DB_PASSWORD}@postgres:5432/migration_checklist"
      MIGRATION_MASTER_KEY: ${MIGRATION_MASTER_KEY:?Set MIGRATION_MASTER_KEY in .env}
      MIGRATION_JWT_SECRET: ${MIGRATION_JWT_SECRET:?Set MIGRATION_JWT_SECRET in .env}
      MIGRATION_EDITION: ${MIGRATION_EDITION:-enterprise}
      MIGRATION_LICENSE_KEY: ${MIGRATION_LICENSE_KEY:-DEV-LOCAL}
      MIGRATION_ENV: ${MIGRATION_ENV:-on-prem}
      MIGRATION_DEPLOYMENT: on-prem
      ENVIRONMENT: ${ENVIRONMENT:-development}
      MIGRATION_ALLOWED_ORIGINS: ${MIGRATION_ALLOWED_ORIGINS:-}
      MIGRATION_LOG_FILE: "0"
    depends_on:
      postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "curl -fsS http://127.0.0.1:8508/health || exit 1"]
      interval: 5s
      timeout: 5s
      retries: 24
      start_period: 90s
    restart: unless-stopped

  ui:
    image: ${SQLOPTIMA_IMAGE_REGISTRY:-ghcr.io/rsharma155}/sqloptima_migration-ui:${SQLOPTIMA_VERSION:-0.2.1}
    ports:
      - "${SQLOPTIMA_UI_PORT:-3508}:3508"
    environment:
      PORT: "3508"
      HOSTNAME: 0.0.0.0
      NEXT_PUBLIC_API_URL: http://localhost:8508
    depends_on:
      api:
        condition: service_started
    restart: unless-stopped

  migration-engine:
    image: ${SQLOPTIMA_IMAGE_REGISTRY:-ghcr.io/rsharma155}/sqloptima_migration-engine:${SQLOPTIMA_VERSION:-0.2.1}
    environment:
      MIGRATION_MASTER_KEY: ${MIGRATION_MASTER_KEY}
      METADATA_DB_HOST: postgres
      METADATA_DB_PORT: "5432"
      METADATA_DB_USER: postgres
      METADATA_DB_NAME: migration_checklist
      METADATA_DB_PASSWORD: ${METADATA_DB_PASSWORD:?Set METADATA_DB_PASSWORD in .env}
      MIGRATION_DATABASE_METADATA_URL: "postgresql://postgres:${METADATA_DB_PASSWORD}@postgres:5432/migration_checklist"
      MIGRATION_QUEUE_PATH: /var/lib/sqloptima/migration_queue.bbolt
      MIGRATION_LOGGING_FORMAT: text
    volumes:
      - sqloptima_queue:/var/lib/sqloptima
    depends_on:
      postgres:
        condition: service_healthy
      api:
        condition: service_started
    restart: unless-stopped

volumes:
  sqloptima_pg:
  sqloptima_queue:
YAML
}

b64_key() {
  if command -v python3 >/dev/null 2>&1; then
    python3 -c "import secrets; print(secrets.token_urlsafe(32))"
  else
    tr -dc 'A-Za-z0-9' </dev/urandom | head -c 48
  fi
}

alnum_password() {
  tr -dc 'A-Za-z0-9' </dev/urandom | head -c 24
}

upsert_env_key() {
  local key="$1"
  local value="$2"
  local tmp
  tmp="$(mktemp)"
  if [[ -f .env ]] && grep -q "^${key}=" .env; then
    awk -v k="$key" -v v="$value" '
      BEGIN { done = 0 }
      $0 ~ "^" k "=" { print k "=" v; done = 1; next }
      { print }
      END { if (!done) print k "=" v }
    ' .env > "$tmp"
    mv "$tmp" .env
  elif [[ -f .env ]]; then
    printf '%s=%s\n' "$key" "$value" >> .env
    rm -f "$tmp"
  else
    rm -f "$tmp"
  fi
}

ensure_env() {
  if [[ ! -f .env ]]; then
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
    return
  fi
  # Keep secrets; always align image tag/registry with this installer so upgrades
  # do not keep pulling unpublished sqloptima_migration-*:0.2.0 images.
  upsert_env_key SQLOPTIMA_VERSION "$VERSION"
  upsert_env_key SQLOPTIMA_IMAGE_REGISTRY "$REGISTRY"
  echo "Using existing $ROOT/.env — image tag set to ${VERSION}."
}

env_get() {
  local key="$1"
  local default="$2"
  local val=""
  if [[ -f .env ]]; then
    val="$(awk -F= -v k="$key" '$1 == k { sub(/^[^=]+=/, ""); print; exit }' .env)"
  fi
  printf '%s\n' "${val:-$default}"
}

host_port_in_use() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -ltn 2>/dev/null | grep -qE ":${port}[[:space:]]"
  elif command -v netstat >/dev/null 2>&1; then
    netstat -ltn 2>/dev/null | grep -qE ":${port}[[:space:]]"
  else
    return 1
  fi
}

explain_port_conflict() {
  local port="$1"
  echo "Host port ${port} is already allocated, so the UI/API cannot bind." >&2
  echo "Containers publishing that port:" >&2
  docker ps --filter "publish=${port}" --format '  {{.Names}}  {{.Ports}}' >&2 || true
  echo >&2
  echo "If this is an old SQL Optima / Grafana / Next.js process:" >&2
  echo "  docker ps --filter publish=${port}" >&2
  echo "  docker compose -p sqloptima_migration down" >&2
  echo "  ss -ltnp | grep ${port}" >&2
  echo "Or keep the other service and remap in $ROOT/.env:" >&2
  echo "  SQLOPTIMA_UI_PORT=3510" >&2
}

compose() {
  local -a dc
  if docker compose version >/dev/null 2>&1; then
    dc=(docker compose)
  elif command -v docker-compose >/dev/null 2>&1; then
    dc=(docker-compose)
  else
    echo "Docker Compose is not available. Install Docker Desktop or Docker Engine, then retry." >&2
    echo "https://docs.docker.com/get-docker/" >&2
    exit 1
  fi
  "${dc[@]}" --project-directory "$ROOT" --env-file "$ROOT/.env" -f "$ROOT/docker-compose.yml" "$@"
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

wait_http() {
  local url="$1"
  local label="$2"
  local i
  for i in $(seq 1 90); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "${label} did not become ready at ${url}." >&2
  return 1
}

wait_stack() {
  wait_http "$API_HEALTH" "API" || {
    echo "API logs:" >&2
    compose logs api --tail 80 >&2 || true
    return 1
  }
  local ui_id
  ui_id="$(compose ps -q ui 2>/dev/null || true)"
  if [[ -z "$ui_id" ]]; then
    echo "The UI container was not created. Full compose status:" >&2
    compose ps -a >&2 || true
    return 1
  fi
  local ui_state
  ui_state="$(docker inspect -f '{{.State.Status}}' "$ui_id" 2>/dev/null || echo missing)"
  if [[ "$ui_state" != "running" ]]; then
    echo "The UI container is ${ui_state}, so http://localhost:${UI_PORT} will not work." >&2
    echo "UI logs:" >&2
    compose logs ui --tail 80 >&2 || true
    echo "Host processes/containers on ${UI_PORT}:" >&2
    docker ps -a --filter "publish=${UI_PORT}" --format '  {{.Names}} {{.Status}} {{.Ports}}' >&2 || true
    return 1
  fi
  if ! docker port "$ui_id" 3508 >/dev/null 2>&1; then
    echo "The UI is running inside Docker but port ${UI_PORT} is not published on the host (empty PORTS in docker ps)." >&2
    echo "Recreating the UI container to attach the host port..." >&2
    compose up -d --force-recreate --no-deps ui || return 1
    ui_id="$(compose ps -q ui 2>/dev/null || true)"
    if ! docker port "$ui_id" 3508 >/dev/null 2>&1; then
      echo "Still no host mapping for ${UI_PORT}. Confirm the compose file has:" >&2
      echo '  ports:' >&2
      echo '    - "${SQLOPTIMA_UI_PORT:-3508}:3508"' >&2
      echo "then: docker compose --env-file .env up -d --force-recreate --no-deps ui" >&2
      return 1
    fi
  fi
  wait_http "$UI_URL" "Dashboard" || wait_http "${UI_URL}/login" "Dashboard" || {
    echo "UI logs:" >&2
    compose logs ui --tail 80 >&2 || true
    return 1
  }
  return 0
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
UI_PORT="$(env_get SQLOPTIMA_UI_PORT 3508)"
API_PORT="$(env_get SQLOPTIMA_API_PORT 8508)"
UI_URL="http://localhost:${UI_PORT}"
API_HEALTH="http://localhost:${API_PORT}/health"

ours_on_port() {
  local port="$1"
  local names
  names="$(docker ps --filter "publish=${port}" --format '{{.Names}}' 2>/dev/null || true)"
  [[ "$names" == *"sqloptima_migration-"* ]]
}

case "$cmd" in
  stop)
    compose down
    echo "SQL Optima Migration stopped. Data is kept in Docker volumes."
    ;;
  status)
    compose ps
    ;;
  start|up|"")
    if host_port_in_use "$UI_PORT" && ! ours_on_port "$UI_PORT"; then
      explain_port_conflict "$UI_PORT"
      exit 1
    fi
    if host_port_in_use "$API_PORT" && ! ours_on_port "$API_PORT"; then
      explain_port_conflict "$API_PORT"
      exit 1
    fi
    echo "Pulling SQL Optima Migration images ${REGISTRY}/sqloptima_migration-*:${VERSION} (no compile on this machine)..."
    compose pull
    if ! compose up -d; then
      echo "Failed to start containers." >&2
      if host_port_in_use "$UI_PORT"; then
        explain_port_conflict "$UI_PORT"
      fi
      echo "API logs:" >&2
      compose logs api --tail 80 >&2 || true
      exit 1
    fi
    echo "Waiting for the app..."
    if ! wait_stack; then
      echo "SQL Optima Migration did not start fully. API may be up at http://localhost:${API_PORT}/health — the dashboard needs a running UI on port ${UI_PORT}." >&2
      exit 1
    fi
    echo
    echo "SQL Optima Migration is running."
    echo "  Dashboard: $UI_URL"
    echo "  API:        http://localhost:${API_PORT}"
    echo "Open the dashboard and create the first admin account."
    open_browser
    ;;
  *)
    echo "Usage: $0 [start|stop|status]" >&2
    exit 1
    ;;
esac
