# Install SQL Optima Migration (Docker only)

End users do **not** clone GitHub, compile code, or install Python / Node / Go.

**Only prerequisite:** [Docker Desktop](https://docs.docker.com/get-docker/) (Windows or macOS) or Docker Engine (Linux). Start Docker and wait until it is running.

## What to put on your website

Host this folder (`deploy/install/`) as a zip, for example:

`https://your-domain.example/sql-optima/sql-optima.zip`

Suggested button copy: **Download SQL Optima Migration** → unzip → run the starter.

You can also host the scripts at stable URLs and use a one-line install (below).

## Windows

1. Install and start [Docker Desktop for Windows](https://docs.docker.com/desktop/setup/install/windows-install/).
2. Download the zip from your website and unzip it (for example to `Downloads\sql-optima`).
3. Double-click `sql-optima.cmd`.

The browser opens **http://localhost:3508**. Create the first admin account on the Setup page.

PowerShell (from the unzipped folder):

```powershell
.\sql-optima.ps1
```

Stop later with `.\sql-optima.ps1 -Stop`.

One-line install once the script is on your site (replace the URL):

```powershell
# Creates %USERPROFILE%\sql-optima, pulls images, starts the app
irm https://your-domain.example/sql-optima/sql-optima.ps1 | iex
```

`irm | iex` runs the copy hosted on **your** site. It does not require GitHub.

## macOS / Linux

1. Install and start Docker Desktop (macOS) or Docker Engine (Linux).
2. Unzip the package, then:

```bash
chmod +x sql-optima.sh
./sql-optima.sh
```

One-liner from your website:

```bash
curl -fsSL https://your-domain.example/sql-optima/sql-optima.sh | bash
```

That installs into `~/sql-optima` unless `SQLOPTIMA_HOME` is set.

## After start

| What | URL |
|------|-----|
| Dashboard | http://localhost:3508 |
| API | http://localhost:8508 |
| OpenAPI | http://localhost:8508/docs |

Source SQL Server and target PostgreSQL are **not** bundled. Add them in **Connections** after login.

Secrets are written to `.env` next to the compose file on first run. Keep that file private. Deleting `.env` without the same keys will make stored connection passwords unreadable.

## Updates

```bash
# Linux / macOS
./sql-optima.sh stop
# edit SQLOPTIMA_VERSION in .env if you pin a newer tag
./sql-optima.sh
```

```powershell
.\sql-optima.ps1 -Stop
.\sql-optima.ps1
```

Images are pulled from `ghcr.io/rsharma155/sqloptima_migration-*` (or `SQLOPTIMA_IMAGE_REGISTRY`). Make those packages **public** in GitHub Packages so customers are not asked to log in to GitHub.

## Website snippet

```html
<h1>Install SQL Optima Migration</h1>
<p>Install Docker Desktop, then download and run. No compilers.</p>
<p><a href="/sql-optima/sql-optima.zip">Download for Windows, macOS, and Linux</a></p>
<p>Windows: unzip and double-click <code>sql-optima.cmd</code>.</p>
<p>macOS/Linux: unzip and run <code>./sql-optima.sh</code>.</p>
```
