# SQL Optima Migration — Docker-only installer. No Python, Node, or Go on the host.
# Usage:
#   .\sql-optima.ps1
#   .\sql-optima.ps1 -Stop
#   .\sql-optima.ps1 -Status
param(
    [switch]$Stop,
    [switch]$Status
)

$ErrorActionPreference = "Stop"
$Version = if ($env:SQLOPTIMA_VERSION) { $env:SQLOPTIMA_VERSION } else { "0.2.1" }
$Registry = if ($env:SQLOPTIMA_IMAGE_REGISTRY) { $env:SQLOPTIMA_IMAGE_REGISTRY } else { "ghcr.io/rsharma155" }
$UiUrl = "http://localhost:3508"
$ApiHealth = "http://localhost:8508/health"

if ($PSScriptRoot) {
    $Root = $PSScriptRoot
} else {
    $Root = if ($env:SQLOPTIMA_HOME) { $env:SQLOPTIMA_HOME } else { Join-Path $HOME "sql-optima" }
    New-Item -ItemType Directory -Force -Path $Root | Out-Null
}

Set-Location $Root

function New-OptimaKey {
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    [Convert]::ToBase64String($bytes)
}

function New-AlnumPassword {
    $chars = [char[]]((48..57) + (65..90) + (97..122))
    $bytes = New-Object byte[] 24
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
}

function Write-ComposeFile {
    $compose = @'
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
      - "8508:8508"
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
      - "3508:3508"
    environment:
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
'@
    $utf8 = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText((Join-Path $Root "docker-compose.yml"), $compose, $utf8)
}

function Set-EnvKey {
    param([string]$Key, [string]$Value)
    $path = Join-Path $Root ".env"
    $lines = @(Get-Content -LiteralPath $path)
    $found = $false
    $out = foreach ($line in $lines) {
        if ($line -match "^$([regex]::Escape($Key))=") {
            $found = $true
            "$Key=$Value"
        } else {
            $line
        }
    }
    if (-not $found) {
        $out = @($out) + "$Key=$Value"
    }
    $utf8 = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($path, (($out -join "`n").Trim() + "`n"), $utf8)
}

function Initialize-EnvFile {
    $path = Join-Path $Root ".env"
    if (Test-Path $path) {
        Set-EnvKey -Key "SQLOPTIMA_VERSION" -Value $Version
        Set-EnvKey -Key "SQLOPTIMA_IMAGE_REGISTRY" -Value $Registry
        Write-Host "Using existing $path — image tag set to $Version."
        return
    }
    $master = New-OptimaKey
    $jwt = New-OptimaKey
    $pg = New-AlnumPassword
    $content = @"
SQLOPTIMA_VERSION=$Version
SQLOPTIMA_IMAGE_REGISTRY=$Registry
MIGRATION_MASTER_KEY=$master
MIGRATION_JWT_SECRET=$jwt
METADATA_DB_PASSWORD=$pg
MIGRATION_EDITION=enterprise
MIGRATION_LICENSE_KEY=DEV-LOCAL
MIGRATION_ENV=on-prem
ENVIRONMENT=development
"@
    $utf8 = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($path, ($content.Trim() + "`n"), $utf8)
    Write-Host "Created $path with generated secrets. Keep this file private."
}

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$ComposeArgs)
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker is required and is the only tool you need to install. See https://docs.docker.com/get-docker/"
    }
    docker compose --project-directory $Root --env-file (Join-Path $Root ".env") -f (Join-Path $Root "docker-compose.yml") @ComposeArgs
}

function Require-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker is required and is the only tool you need to install.`nInstall Docker Desktop: https://docs.docker.com/desktop/setup/install/windows-install/"
    }
    try {
        docker info | Out-Null
    } catch {
        throw "Docker is installed but not running. Start Docker Desktop, wait until it is ready, then retry."
    }
}

function Wait-Healthy {
    for ($i = 0; $i -lt 90; $i++) {
        try {
            Invoke-WebRequest -Uri $ApiHealth -UseBasicParsing -TimeoutSec 5 | Out-Null
            return
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    Write-Warning "SQL Optima Migration started but the API is not healthy yet. API logs:"
    Invoke-Compose logs api --tail 80
}

Require-Docker
Write-ComposeFile
Initialize-EnvFile

if ($Stop) {
    Invoke-Compose down
    Write-Host "SQL Optima Migration stopped. Data is kept in Docker volumes."
    return
}

if ($Status) {
    Invoke-Compose ps
    return
}

Write-Host "Pulling SQL Optima Migration images (no compile on this machine)..."
Invoke-Compose pull
try {
    Invoke-Compose up -d
} catch {
    Write-Warning "Failed to start containers. API logs:"
    Invoke-Compose logs api --tail 80
    throw
}
Write-Host "Waiting for the app..."
Wait-Healthy
Write-Host ""
Write-Host "SQL Optima Migration is running."
Write-Host "  Dashboard: $UiUrl"
Write-Host "  API:        http://localhost:8508"
Write-Host "Open the dashboard and create the first admin account."
Start-Process $UiUrl
