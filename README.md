# AdaptaAI

**AI platform that helps employers onboard and adapt labor migrants.**

AdaptaAI connects two sides: a multilingual PWA for migrants (AI chat, onboarding hub, help requests) and an HR/employer dashboard (invite workers, upload company docs, monitor progress, handle escalations). A RAG pipeline answers questions in Hindi, Russian, and English from employer-uploaded documents and a shared knowledge base.

---

## Features

### B2C — Migrant App (PWA)
- Guided onboarding flow (passport upload, registration steps)
- AI chat assistant with multilingual Q&A (Hindi / Russian / English)
- Script detection and automatic query canonicalization (Qwen 2.5)
- Answers grounded in employer documents and partner knowledge base, with source citations
- Emergency/escalation detection — critical messages bypass RAG and route to HR immediately
- Help request submission and status tracking
- Documents, finance, and life-in-Russia info pages
- PWA manifest + service worker for installable mobile experience

### B2B — HR / Employer Dashboard
- Invite workers via email (tokenized invite links, 7-day TTL)
- Upload company documents (PDF / DOCX) for RAG ingestion
- Monitor worker onboarding progress and journey stages
- Escalations inbox with severity triage
- Foreman scan (QR-based worker lookup)
- Partner products knowledge base

---

## Architecture

```
                    ┌──────────────────────────────────────┐
                    │          Docker Compose               │
                    │                                       │
  Browser           │  ┌───────────────────────────────┐   │
  ┌──────────┐      │  │   FastAPI  api :8000           │   │
  │  b2c/    │◄─────┼──┤   • REST + SSE endpoints       │   │
  │  (PWA)   │      │  │   • Static file serving        │   │
  └──────────┘      │  │   • JWT auth + invite flow     │   │
  ┌──────────┐      │  │   • RAG pipeline               │   │
  │  b2b/    │◄─────┼──┤   • Emergency escalation       │   │
  │  (HR UI) │      │  └──────┬───────────┬─────────────┘   │
  └──────────┘      │         │           │                  │
                    │  ┌──────▼───┐  ┌────▼──────────────┐  │
                    │  │Postgres  │  │ ChromaDB           │  │
                    │  │   16     │  │ embedded vector    │  │
                    │  │ users /  │  │ store              │  │
                    │  │ docs /   │  │ (multilingual-e5   │  │
                    │  │ threads  │  │  embeddings)       │  │
                    │  └──────────┘  └───────────────────-┘  │
                    │  ┌───────────────────────────────────┐  │
                    │  │  MailHog :1025/:8025  (dev SMTP)  │  │
                    │  └───────────────────────────────────┘  │
                    └──────────────────────────────────────--┘
                                  │
                    ┌─────────────┴─────────────┐
                    │  External LLM APIs         │
                    │  GigaChat-2-Pro            │
                    │    answer generation        │
                    │  Qwen 2.5-72B / OpenRouter  │
                    │    translation, canonical.  │
                    └────────────────────────────┘
```

For a detailed component and request-flow diagram, see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend framework | FastAPI 0.115, Python 3.11 |
| Database | PostgreSQL 16 (asyncpg + SQLAlchemy 2) |
| Migrations | Alembic 1.14 |
| Vector store | ChromaDB ≥ 1.0 (embedded) |
| Embeddings | `intfloat/multilingual-e5-base` (sentence-transformers) |
| Document parsing | pypdf 5, python-docx 1.2 |
| Chunking | langchain-text-splitters 0.3 |
| Answer generation | GigaChat-2-Pro |
| Translation / canonicalization | Qwen 2.5-72B via OpenRouter |
| Auth | JWT (PyJWT), invite tokens |
| Email (dev) | MailHog |
| Package manager | uv |
| Linting | ruff |
| Tests | pytest-asyncio, testcontainers |
| Frontend | Static HTML/JS/CSS (no build step required) |
| Infrastructure | Docker Compose (3 services) |

---

## Quick Start

### Prerequisites
- Docker + Docker Compose
- GigaChat API key (from the Sber developer portal)
- OpenRouter API key (for Qwen 2.5)

### Steps

```bash
# 1. Clone
git clone https://github.com/Qusto/adapta-ai.git
cd adapta-ai

# 2. Configure
cp infra/.env.example infra/.env
# Edit infra/.env — fill in at minimum:
#   GIGACHAT_AUTHORIZATION_KEY, OPENROUTER_API_KEY,
#   POSTGRES_PASSWORD, JWT_SECRET, INVITE_SECRET

# 3. Start services  (builds the API image, starts postgres + mailhog)
make up

# 4. Seed demo data  (creates an HR account, demo company, sample workers)
make seed-demo

# 5. Open the apps
#   B2B HR dashboard : http://localhost:8000/b2b/15-hr-dashboard.html
#   B2C migrant app  : http://localhost:8000/b2c/01-welcome.html
#   MailHog (dev email): http://localhost:8025
#   API docs (Swagger): http://localhost:8000/docs

# 6. Run tests
make test
```

Seed the shared partner-products knowledge base (optional):

```bash
make seed-sber
```

Tear down everything including data volumes:

```bash
make reset
```

---

## Repo Structure

```
adapta-ai/
├── backend/                  # FastAPI application
│   ├── app/
│   │   ├── api/v1/           # Route handlers (auth, chat, documents, invites, …)
│   │   ├── auth/             # JWT, invite tokens, password hashing
│   │   ├── chat/             # Message handler, SSE streamer, schemas
│   │   ├── rag/              # RAG pipeline (loader→chunker→embedder→store→retriever)
│   │   ├── llm/              # GigaChat client, Qwen client, prompt builder
│   │   ├── email/            # Email templates, MailHog client
│   │   ├── db/               # SQLAlchemy models
│   │   ├── middleware/       # Static auth middleware
│   │   ├── workers/          # Background worker helpers
│   │   ├── config.py         # Pydantic settings (reads infra/.env)
│   │   ├── database.py       # Async engine + session factory
│   │   └── main.py           # App factory, router registration
│   ├── migrations/           # Alembic migration versions
│   ├── tests/                # unit/, integration/, e2e/, rag_smoke/, perf/
│   ├── scripts/              # seed_demo, seed_partner_products, eval_rag, smoke helpers
│   ├── pyproject.toml
│   └── Dockerfile
├── b2c/                      # Migrant PWA (static HTML/JS, screens 01–14)
│   ├── manifest.json
│   ├── sw.js
│   └── 01-welcome.html … 14-profile.html
├── b2b/                      # HR/employer dashboard (static HTML/JS, screens 15–20)
│   └── 15-hr-dashboard.html … 20-sber-products.html
├── infra/
│   ├── docker-compose.yml
│   ├── .env.example          # Configuration template (copy to infra/.env)
│   └── certs/                # Russian TLS CA bundle (required for GigaChat)
├── scripts/                  # Shell smoke tests (gigachat-smoke.sh, qwen-smoke.sh)
├── design-tokens.css         # Shared CSS design tokens
├── i18n.js                   # Frontend i18n strings (RU / HI / EN)
├── mock-data.js              # Demo data for frontend development
├── index.html                # Root landing page
├── Makefile
├── LICENSE                   # Apache-2.0 (code)
└── LICENSE-DATA              # CC-BY-4.0 (dataset)
```

---

## Configuration

All runtime configuration lives in `infra/.env` (gitignored). Copy from the template and fill in the required values. Never commit real secrets.

| Variable | Purpose |
|---|---|
| `GIGACHAT_AUTHORIZATION_KEY` | Base64 authorization key from the Sber developer cabinet |
| `GIGACHAT_SCOPE` | GigaChat API scope (`GIGACHAT_API_PERS` or `GIGACHAT_API_CORP`) |
| `GIGACHAT_MODEL` | GigaChat model name (default: `GigaChat-2-Pro`) |
| `OPENROUTER_API_KEY` | OpenRouter key for Qwen 2.5 access |
| `QWEN_MODEL` | Qwen model slug on OpenRouter (default: `qwen/qwen-2.5-72b-instruct`) |
| `POSTGRES_PASSWORD` | Postgres password (must also match `DATABASE_URL`) |
| `DATABASE_URL` | Full async database URL |
| `JWT_SECRET` | Secret for signing JWT access tokens — `openssl rand -hex 32` |
| `INVITE_SECRET` | Secret for signing invite tokens — `openssl rand -hex 32` |
| `ADAPTA_DEMO_ENABLED` | Set `true` to enable the demo login endpoint |
| `ADAPTA_DEMO_PASSWORD` | Password for the demo HR account |
| `EMBEDDING_MODEL` | HuggingFace model ID for embeddings (default: `intfloat/multilingual-e5-base`) |
| `CHROMA_PERSIST_PATH` | ChromaDB storage path inside the container |
| `RAGAS_JUDGE_MODEL` | LLM judge for RAG evaluation (default: `google/gemini-2.5-flash` via OpenRouter) |
| `SMTP_HOST` / `SMTP_PORT` / … | Optional: override MailHog with a real SMTP server |

See `infra/.env.example` for the full list with inline comments.

---

## Dataset

The companion evaluation dataset is published separately on HuggingFace:

**[https://huggingface.co/datasets/Qusto/adapta-migrant-onboarding](https://huggingface.co/datasets/Qusto/adapta-migrant-onboarding)**

Mirror on GitHub: [github.com/Qusto/adapta-ai-dataset](https://github.com/Qusto/adapta-ai-dataset)

Licensed under **CC-BY-4.0** (see `LICENSE-DATA`).

---

## License

- **Code** — Apache License 2.0. See [LICENSE](LICENSE).
- **Data** — Creative Commons Attribution 4.0 International. See [LICENSE-DATA](LICENSE-DATA).

---

## Status / Disclaimer

AdaptaAI is an **MVP / research prototype**. It demonstrates end-to-end RAG-based multilingual onboarding but is **not production-hardened**:

- No rate limiting on public endpoints.
- Email delivery uses MailHog by default (development only).
- The Russian TLS CA bundle for GigaChat is included for development convenience.
- Demo mode (`ADAPTA_DEMO_ENABLED=true`) bypasses normal invite-based registration.

Use in production at your own risk and after a proper security review.

---

## Краткое описание (RU)

AdaptaAI — AI-платформа адаптации трудовых мигрантов. Работодатель загружает корпоративные документы, приглашает работников по email. Мигрант получает PWA с чатом на хинди / русском / английском, который отвечает на вопросы по документам компании и общей базе знаний (RAG). Критичные сообщения автоматически эскалируются в HR. Технически: FastAPI + Postgres + ChromaDB + GigaChat-2-Pro + Qwen 2.5.
