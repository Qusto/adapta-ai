# AdaptaAI — Backend

FastAPI 0.115 application. Serves the REST + SSE API, statically hosts the `b2c/` and `b2b/` frontends, runs the RAG pipeline, and talks to GigaChat and Qwen via external APIs.

---

## Directory Layout (`backend/app/`)

```
app/
├── api/v1/             # FastAPI routers — one file per resource
│   ├── auth.py         # /auth/login, /auth/me
│   ├── chat.py         # POST /chat  (SSE streaming answer)
│   ├── chat_escalations.py
│   ├── chat_stats.py
│   ├── chat_threads.py
│   ├── company.py      # /company/me
│   ├── demo.py         # demo-mode login (ADAPTA_DEMO_ENABLED)
│   ├── docs_login.py
│   ├── documents.py    # upload / list / delete company documents
│   ├── invites.py      # create + accept invite links
│   ├── journey.py      # onboarding journey stages
│   └── workers.py      # HR: list/view workers
│
├── auth/               # Authentication helpers
│   ├── jwt.py          # token creation + verification
│   ├── invite.py       # invite-token signing + verification
│   ├── password.py     # bcrypt hashing
│   └── deps.py         # FastAPI dependency injectors (current_user, etc.)
│
├── chat/               # Chat pipeline
│   ├── message_handler.py   # orchestrates RAG → LLM → escalation check
│   ├── sse_streamer.py      # streams tokens via Server-Sent Events
│   ├── router.py
│   └── schemas.py
│
├── rag/                # RAG pipeline stages
│   ├── loader.py       # PDF / DOCX → raw text
│   ├── chunker.py      # RecursiveCharacterTextSplitter via langchain
│   ├── embedder.py     # multilingual-e5-base via sentence-transformers
│   ├── store.py        # ChromaDB add / delete collections
│   ├── retriever.py    # semantic search, top-k, confidence filter
│   ├── normalize.py    # ё-normalization, whitespace cleanup
│   ├── answer_parser.py
│   ├── prompts.py
│   ├── factory.py
│   └── schemas.py
│
├── llm/                # LLM clients
│   ├── gigachat_client.py   # GigaChat-2-Pro (answer generation)
│   ├── qwen_client.py       # Qwen 2.5-72B via OpenRouter (translation, canonicalization)
│   ├── qwen_prompts.py
│   ├── prompt_builder.py
│   └── fallback.py
│
├── email/              # Email sending
│   ├── mailhog_client.py    # aiosmtplib wrapper
│   └── templates/           # Jinja2 email templates
│
├── db/
│   └── models.py       # SQLAlchemy ORM models
│
├── middleware/
│   └── static_auth.py  # optional HTTP Basic auth on static routes
│
├── workers/            # Background / async worker helpers
│
├── config.py           # Pydantic Settings — reads infra/.env
├── database.py         # Async engine + sessionmaker
└── main.py             # App factory: mounts routers, static files, middleware
```

---

## RAG Pipeline

When an HR user uploads a document the pipeline runs synchronously on the `/documents` endpoint:

```
Upload (PDF / DOCX)
  └─► loader.py       — extract raw text per page/paragraph
        └─► normalize.py  — ё-normalization, whitespace cleanup
              └─► chunker.py   — split into overlapping chunks
                    └─► embedder.py  — multilingual-e5-base embeddings
                          └─► store.py  — upsert into ChromaDB collection keyed by company_id
```

When a migrant sends a chat message:

```
Incoming message
  └─► script detection  — detect Hindi / Russian / other
        └─► qwen_client  — canonicalize / translate query to Russian
              └─► retriever.py  — embed query, top-k cosine search in company collection
                    └─► confidence gate  — low-confidence → "not found" answer
                          └─► gigachat_client  — generate answer with retrieved chunks as context
                                └─► answer_parser  — extract citations, format response
                                      └─► escalation check  — keyword detector → severity flag
                                            └─► SSE stream to client
```

---

## Migrations (Alembic)

Migrations live in `backend/migrations/versions/`. The app applies them automatically on startup via `alembic upgrade head`.

To create a new migration after changing `app/db/models.py`:

```bash
cd backend
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head   # apply locally (or restart the container)
```

---

## Running Tests

```bash
cd backend
uv sync --dev           # install all dev dependencies

# Full test suite
uv run pytest tests/ -v

# Unit tests only (no external services required)
uv run pytest tests/unit -v

# Integration tests (require a running Postgres — uses testcontainers automatically)
uv run pytest tests/integration -v -m integration
```

Or via Make from the repo root:

```bash
make test            # uv run pytest tests/
make test-unit       # tests/unit only
make test-integration
```

Test layout:

```
tests/
├── unit/           # pure logic, mocked dependencies
├── integration/    # database + Alembic, uses testcontainers
├── e2e/            # Playwright end-to-end (requires running stack)
├── rag_smoke/      # RAG smoke queries against a live stack
└── perf/           # performance / load tests
```

---

## Linting

```bash
cd backend
uv run ruff check .    # lint
uv run ruff format .   # format
```

Line length: 100. Target: Python 3.11. Config in `pyproject.toml` under `[tool.ruff]`.
