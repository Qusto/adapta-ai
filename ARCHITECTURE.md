# AdaptaAI — Architecture

This document describes the components, request flows, data model, and deployment topology of AdaptaAI.

---

## Components

```mermaid
graph TD
    subgraph Browser
        B2C["b2c/ — Migrant PWA\n(static HTML/JS)"]
        B2B["b2b/ — HR Dashboard\n(static HTML/JS)"]
    end

    subgraph api ["FastAPI  api :8000"]
        STATIC["StaticFiles\n/b2c  /b2b"]
        ROUTER["REST + SSE Routers\n/api/v1/..."]
        AUTH["auth/\nJWT + invite tokens"]
        CHAT["chat/\nmessage_handler\nsse_streamer"]
        RAG["rag/\nloader → chunker\nembedder → store\nretriever"]
        LLM["llm/\ngigachat_client\nqwen_client"]
        EMAIL["email/\nmailhog_client"]
    end

    subgraph infra ["Infrastructure (docker-compose)"]
        PG["PostgreSQL 16\nusers / companies\ndocuments / threads\nmessages / invites"]
        CHROMA["ChromaDB\nembedded vector store\nmultilingual-e5-base"]
        MAILHOG["MailHog\nSMTP :1025\nWeb UI :8025"]
    end

    subgraph ext ["External APIs"]
        GIGACHAT["GigaChat-2-Pro\nanswer generation"]
        QWEN["Qwen 2.5-72B\nvia OpenRouter\ntranslation / canonicalization"]
    end

    B2C -->|HTTP fetch / SSE| ROUTER
    B2B -->|HTTP fetch| ROUTER
    Browser -->|"GET /b2c/* /b2b/*"| STATIC

    ROUTER --> AUTH
    ROUTER --> CHAT
    ROUTER --> RAG
    ROUTER --> EMAIL

    CHAT --> RAG
    CHAT --> LLM

    AUTH --> PG
    CHAT --> PG
    RAG --> CHROMA
    RAG --> PG
    EMAIL --> MAILHOG
    LLM --> GIGACHAT
    LLM --> QWEN
```

---

## Request Flow 1 — HR Uploads a Document

An employer uploads a PDF or DOCX through the HR dashboard (`/api/v1/documents`).

```mermaid
sequenceDiagram
    participant HR as HR Browser (b2b/)
    participant API as FastAPI
    participant RAG as rag/ pipeline
    participant PG as PostgreSQL
    participant C as ChromaDB

    HR->>API: POST /api/v1/documents  (multipart, JWT)
    API->>API: auth.deps — verify JWT, get company_id
    API->>PG: INSERT document record (filename, status=processing)
    API->>RAG: ingest(file_bytes, company_id)

    RAG->>RAG: loader.py — extract raw text (pypdf / python-docx)
    RAG->>RAG: normalize.py — ё-normalization, whitespace cleanup
    RAG->>RAG: chunker.py — RecursiveCharacterTextSplitter
    RAG->>RAG: embedder.py — multilingual-e5-base → vectors
    RAG->>C: store.py — upsert chunks into company collection

    RAG-->>API: chunk count
    API->>PG: UPDATE document status=indexed, chunk_count=N
    API-->>HR: 201 { id, chunk_count }
```

---

## Request Flow 2 — Migrant Asks a Question

A migrant types a question in the PWA chat. The answer streams back via Server-Sent Events.

```mermaid
sequenceDiagram
    participant MIG as Migrant Browser (b2c/)
    participant API as FastAPI
    participant CH as chat/
    participant LLM as llm/
    participant RAG as rag/
    participant C as ChromaDB
    participant PG as PostgreSQL
    participant QWEN as Qwen 2.5
    participant GC as GigaChat-2-Pro

    MIG->>API: POST /api/v1/chat  { message, thread_id }
    API->>API: verify JWT, get user / company_id
    API->>PG: INSERT user message into thread

    API->>CH: message_handler(message, company_id, lang)

    CH->>CH: script detection (Hindi / Russian / other)
    CH->>QWEN: canonicalize / translate query to Russian
    QWEN-->>CH: canonical_query

    CH->>RAG: retriever.retrieve(canonical_query, company_id, top_k=5)
    RAG->>RAG: embedder.embed(canonical_query)
    RAG->>C: cosine search in company collection
    C-->>RAG: top-k chunks + scores
    RAG->>RAG: confidence gate — low score → no-context path
    RAG-->>CH: context_chunks

    CH->>LLM: prompt_builder.build(query, context_chunks, lang)
    CH->>GC: generate(prompt) — streaming
    GC-->>CH: token stream

    CH->>CH: answer_parser — extract citations
    CH->>CH: escalation check — keyword detector
    Note over CH: escalate=True → set severity=critical,\nroute copy to HR inbox

    CH-->>API: token stream + metadata
    API-->>MIG: SSE stream (text/event-stream)
    API->>PG: INSERT assistant message (full text, citations, escalated flag)
```

---

## Data Model Summary

| Table | Key columns | Notes |
|---|---|---|
| `users` | id, email, role (hr/migrant), company_id, hashed_password | invite-based registration |
| `companies` | id, name, logo_url | created by HR on signup |
| `invites` | id, token_hash, company_id, expires_at, used_at | 7-day TTL signed tokens |
| `documents` | id, company_id, filename, status, chunk_count | status: pending/indexed/error |
| `chat_threads` | id, user_id, company_id, created_at | one thread per conversation |
| `chat_messages` | id, thread_id, role, content, citations, escalated, severity | full message history |
| `journey_steps` | id, user_id, step_key, completed_at | onboarding progress tracking |

ChromaDB stores vector chunks in a **per-company collection** (`company_{id}`). Each chunk document stores `source_doc_id`, `page`, and `chunk_index` as metadata for citation reconstruction.

---

## Deployment Topology

The full stack runs via a single `docker-compose.yml` in `infra/`. Three services:

```
┌─────────────────────────────────────────────────────┐
│  docker-compose  (infra/)                           │
│                                                     │
│  ┌──────────────────────────────────────────────┐   │
│  │  api  (adapta-api image, port 8000)          │   │
│  │  • builds from backend/Dockerfile            │   │
│  │  • mounts b2c/, b2b/ as read-only volumes    │   │
│  │  • mounts backend/app for hot-reload         │   │
│  │  • api_data volume → ChromaDB + uploads      │   │
│  │  • reads infra/.env                          │   │
│  └──────────────────┬──────────────────────────-┘   │
│                     │                               │
│  ┌──────────────────▼──────┐  ┌──────────────────┐  │
│  │  postgres :5432         │  │  mailhog          │  │
│  │  postgres:16-alpine     │  │  :1025 (SMTP)     │  │
│  │  postgres_data volume   │  │  :8025 (Web UI)   │  │
│  └─────────────────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────┘
```

The `api` service depends on `postgres` (health-checked) and `mailhog`. On startup, `alembic upgrade head` runs automatically. ChromaDB runs **embedded** inside the `api` process — no separate service is needed.

For production deployment, replace MailHog with a real SMTP server (`SMTP_HOST`, `SMTP_PORT`, etc. in `.env`) and consider adding a reverse proxy (nginx/Caddy) in front of the `api` container.
