# Contributing to SQL Optima

Thank you for your interest in contributing to [SQL Optima](https://github.com/rsharma155/sqloptima_migration).

## Getting started

### One-command local setup

From a clean machine (Python 3.11+, Node.js 18+, Go 1.23+ recommended):

```bash
git clone https://github.com/rsharma155/sqloptima_migration.git && cd sqloptima_migration && python3 start.py --all
```

For development without starting servers:

```bash
python3 start.py --setup
```

### Manual setup

```bash
git clone https://github.com/rsharma155/sqloptima_migration.git
cd sqloptima_migration
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev,full]"
cd apps/ui && npm install && cd ../..
```

> **Mac ↔ Windows shared folders:** `node_modules` is not portable by default
> (native binaries for rolldown / lightningcss / Next SWC). This repo's
> `apps/ui` postinstall runs `ensure-native-bindings.mjs`, which force-installs
> Mac + Windows + Linux optional bindings into the same tree.
>
> After copying a repo between Mac and Windows (or if vitest fails with
> `Cannot find native binding`), run:
>
> ```bash
> cd apps/ui && npm ci && npm run deps:native:all
> ```
>
> Prefer not syncing `node_modules` across OSes; commit only `package-lock.json`.

## Development workflow

1. **Fork** the repository and create a feature branch from `main`.
2. **Make focused changes** — one logical fix or feature per pull request.
3. **Run tests** before opening a PR (see below).
4. **Open a pull request** with a clear description of what changed and why.

## Running tests

```bash
# Python unit + integration tests
pip install -e ".[dev]"
python -m pytest tests/ -v

# With coverage
python -m pytest --cov=. --cov-report=term-missing

# Go data plane (no live DB required)
# Windows: ensure "C:\Program Files\Go\bin" is on PATH
cd engine-go && go test ./...

# UI lint
cd apps/ui && npm run lint

# UI unit tests (vitest) — run npm ci / npm run deps:native first on this OS
cd apps/ui && npm test
```

### Windows Go PATH tip

If `go` is not found after installing Go, add `C:\Program Files\Go\bin` to your
user PATH (or run `$env:PATH = "C:\Program Files\Go\bin;$env:PATH"` in the
current PowerShell session).

## Code style

Python:

```bash
ruff check .
ruff format .
mypy .
```

Guidelines:

- **SQL transformations must use AST nodes** — no regex-based SQL rewriting in domain code.
- **Parameterized queries** for all user-supplied data in validation and replication paths.
- **Match existing patterns** in the file you edit (naming, layering, import style).
- Keep diffs minimal; avoid unrelated refactors in the same PR.

## Architecture

Read [ARCHITECTURE.md](ARCHITECTURE.md) before touching cross-layer code. The dependency rule is: API → application services → domain + infrastructure ports → shared kernel. Domain code must not import FastAPI or SQLAlchemy models.

## Pull request checklist

- [ ] Tests pass locally (`pytest`, and `go test ./...` if you changed `engine-go/`)
- [ ] New behavior has tests when the change is non-trivial
- [ ] No secrets, `.env` files, or credentials committed
- [ ] PR description explains the problem and the approach

## Security

Report vulnerabilities privately — see [SECURITY.md](SECURITY.md). Do not open public issues for security bugs.

## Questions

Open a [GitHub Discussion](https://github.com/rsharma155/sqloptima_migration/discussions) or file an issue for bugs and feature requests.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
