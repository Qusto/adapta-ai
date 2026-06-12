# Contributing to AdaptaAI

Thanks for your interest in contributing. Contributions of all kinds are welcome — bug reports, documentation improvements, and code changes. All contributions are accepted under the Apache-2.0 license (see LICENSE).

---

## Setting Up a Development Environment

### Requirements
- Python 3.11 (exactly — the project pins `>=3.11,<3.12`)
- [uv](https://github.com/astral-sh/uv) package manager
- Docker + Docker Compose (for running the full stack)
- Node.js (only if you want to regenerate architecture diagrams via `make diagrams`)

### Steps

```bash
# 1. Fork + clone
git clone https://github.com/<YOUR_FORK>/adapta-ai.git
cd adapta-ai

# 2. Install backend dependencies (including dev extras)
cd backend
uv sync --dev

# 3. Install pre-commit hooks
pip install pre-commit   # or: uv tool install pre-commit
pre-commit install

# 4. Set up infra
cp infra/.env.example infra/.env
# Fill in at minimum: GIGACHAT_AUTHORIZATION_KEY, OPENROUTER_API_KEY,
# POSTGRES_PASSWORD, JWT_SECRET, INVITE_SECRET

# 5. Start the stack
make up
make seed-demo
```

The API will be available at `http://localhost:8000`. Swagger UI is at `/docs`.

---

## Running Tests

```bash
# From the repo root:
make test               # full suite (unit + integration)
make test-unit          # unit tests only (no Docker required)
make test-integration   # integration tests (testcontainers spins up Postgres)

# Or directly from backend/:
cd backend
uv run pytest tests/ -v
```

Integration tests use [testcontainers](https://github.com/testcontainers/testcontainers-python) to spin up a real Postgres instance — no manual setup needed.

---

## Pre-commit Hooks

The project uses [pre-commit](https://pre-commit.com/) with two hooks, configured in `.pre-commit-config.yaml`:

| Hook | What it does |
|---|---|
| `ruff check --fix` | Lint Python files under `backend/app`, `backend/scripts`, `backend/migrations` |
| `ruff-format` | Auto-format the same paths |
| `mypy --strict` | Type-check `backend/app` |

Run all hooks manually:

```bash
pre-commit run --all-files
```

If a hook fails on your commit, fix the reported issues, `git add` the changed files, and commit again.

---

## Code Style

- **Formatter / linter**: [ruff](https://docs.astral.sh/ruff/). Line length 100, Python 3.11 target.
- **Type checking**: mypy with `--strict`. All public functions should have type annotations.
- **Python version**: 3.11 only. Do not use features from 3.12+.
- **Imports**: isort order enforced by ruff (`I` rules). Absolute imports preferred.
- **Frontend**: plain HTML/CSS/JS, no build toolchain. Keep it simple.

---

## Branch and PR Conventions

- Branch naming: `feat/<short-description>`, `fix/<short-description>`, `docs/<short-description>`, `chore/<short-description>`.
- Keep PRs focused — one logical change per PR.
- Write a short description in the PR body explaining *why*, not just *what*.
- All tests must pass (CI runs `make test`).
- All pre-commit hooks must pass before merging.
- New backend endpoints should include at least a unit test.

---

## Smoke-Testing External APIs

After wiring up keys in `infra/.env`, you can verify connectivity to the LLM providers:

```bash
make gigachat-smoke   # hits GigaChat with a minimal request
make qwen-smoke       # hits Qwen via OpenRouter
make smoke            # checks that the API /healthz endpoint returns ok
```

---

## Reporting Issues

Please open a GitHub issue with:
- A clear title and description.
- Steps to reproduce (for bugs).
- The relevant section of `docker-compose logs api` if it's a runtime error.
- Your OS, Python version, and Docker version.
