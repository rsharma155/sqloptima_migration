# Security Policy

## Supported versions

Security fixes are applied to the default branch of [sqloptima_migration](https://github.com/rsharma155/sqloptima_migration). There is no separate LTS release line at this time.

| Version / branch | Supported |
|:-----------------|:---------:|
| `main` (latest)  | ✅        |

## Reporting a vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

If you discover a security issue, report it privately:

1. Open a **[GitHub Security Advisory](https://github.com/rsharma155/sqloptima_migration/security/advisories/new)** (preferred), or
2. Email the maintainer with a description, steps to reproduce, and impact assessment.

Include:

- Affected component (API, UI, Go engine, replication, etc.)
- Proof of concept or minimal reproduction steps
- Whether the issue is exploitable without authentication (if known)

We aim to acknowledge reports within **5 business days** and will coordinate disclosure once a fix is available.

## Scope

In scope:

- Authentication and authorization bypass
- SQL injection or unsafe dynamic SQL in platform code
- Credential exposure, weak cryptography, or secrets handling flaws
- Remote code execution or privilege escalation in the platform stack

Out of scope (unless they enable the above):

- Misconfiguration of `.env` or deployment settings by operators
- Vulnerabilities in third-party dependencies already tracked by Dependabot / `security-audit.yml`
- Denial-of-service from intentionally large conversion payloads within documented rate limits

## Production hardening

For deployment checklists (encryption at rest, JWT rotation, least-privilege DB grants, supply-chain audits), see [docs/SECURITY.md](docs/SECURITY.md) when the local `docs/` tree is present, and follow [OPERATIONS.md](OPERATIONS.md) / [PACKAGING.md](PACKAGING.md) for runtime controls.

Key platform controls already in the product:

- SecretsManager Fernet + per-encrypt PBKDF2 salt (`MIGRATION_MASTER_KEY` required)
- JWT HS256 (default) or optional RS256; dual-secret rotation via `MIGRATION_JWT_SECRET_PREVIOUS`
- Role hierarchy `viewer` < `operator` < `admin`; project scoping for non-admin JWTs
- Parameterized SQL in validation and replication apply paths
- Elevated DB principal hard-fail unless `MIGRATION_ALLOW_ELEVATED_PRIVILEGES=1`

## Security-related CI

- `.github/workflows/security-audit.yml` — weekly `pip-audit` and `npm audit`
- `.github/dependabot.yml` — dependency update PRs
- `scripts/generate_sbom.py` — SBOM generation for release artifacts
- `.github/workflows/publish-images.yml` — GHCR images + `sqloptima_migration-install.zip`
