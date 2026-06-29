# Sprint 1: Infrastructure, LLM Routing, and Architecture Diagrams

This branch contains the Sprint 1 foundation work for the multi-user, multi-domain RAG MVP.

## Scope

This package covers the assigned Sprint 1 tasks:

- ADR: LLM Routing
- Monorepo skeleton
- CI/CD skeleton
- Docker Compose local stack
- Architecture diagrams

## Folder Layout

```text
.github/workflows/ci.yml
backend/
docs/
  adr/
  architecture/
frontend/
infrastructure/
  docker/
shared/
```

## Local Run

From the repository root:

```powershell
docker compose -f infrastructure/docker/docker-compose.yml up --build
```

Useful URLs:

- API health: http://localhost:8000/health
- API docs: http://localhost:8000/docs
- Frontend placeholder: http://localhost:3000

## Sprint 4 Security and Governance

Production-readiness guidance is documented here:

- [TLS and secrets management](docs/security/tls-and-secrets-management.md)
- [AI governance and responsible use policy](docs/governance/responsible-use-policy.md)

For a domain-backed HTTPS deployment, configure `.env` from `.env.production.example` and add the TLS compose overlay:

```powershell
docker compose -p rag-main `
  -f infrastructure/docker/docker-compose.yml `
  -f infrastructure/docker/docker-compose.tls.yml `
  up -d --build
```

The Compose stack is intentionally minimal for Sprint 1. Vector DB, graph DB, auth, workers, and observability are shown in diagrams as integration points, but not locked into Docker services until their ADRs are approved.

## Backend Test Run

```powershell
python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
python -m pytest
```

## Main Sprint 1 Decisions

The LLM router is domain-aware and safe by default:

- If any selected domain requires `local`, the request uses `Qwen/Qwen3-8B` in 4-bit on a Colab-hosted endpoint.
- If all selected domains allow `api`, the request uses Gemini `gemini-3.5-flash`.
- If routing metadata is missing or invalid, the request defaults to `local`.

See [ADR 0001](docs/adr/0001-llm-routing.md) for the full decision record.

## Diagrams

Architecture diagrams are in [docs/architecture/README.md](docs/architecture/README.md).

They include:

- Sprint 1 walking skeleton
- System context
- Container view
- Query flow
- Ingestion flow
- LLM routing flow
- CI/CD flow

---

# Fixed-Solutions-OpenData-Internship

# RAG Platform — Backend

Multi-User Multi-Domain RAG System backend built with FastAPI, Keycloak, and PostgreSQL.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Project Structure](#project-structure)
3. [Environment Setup](#environment-setup)
4. [Keycloak Setup](#keycloak-setup)
5. [Database Setup](#database-setup)
6. [Running the Stack Locally](#running-the-stack-locally)
7. [OCR Support](#ocr-support)
8. [API Endpoints](#api-endpoints)
9. [Postman Testing Guide](#postman-testing-guide)

---

## Prerequisites

Make sure the following are installed before starting:

- Python 3.11+
- Docker Desktop
- PostgreSQL (local install or via Docker)
- Postman

---

## Project Structure

```
backend/
├── app/
│   ├── main.py                        # FastAPI app entry point
│   ├── models/
│   │   ├── user.py                    # User model + Role enum
│   │   └── domain.py                  # Domain + UserDomainRole models
│   ├── schemas/
│   │   ├── user.py                    # User response schemas
│   │   └── domain.py                  # Domain request/response schemas
│   ├── core/
│   │   ├── config.py                  # Environment variables
│   │   ├── database.py                # SQLAlchemy engine + session
│   │   └── security.py                # JWT validation + role guards
│   ├── api/v1/
│   │   ├── dependencies/
│   │   │   └── auth.py                # Auth dependency re-exports
│   │   └── endpoints/
│   │       ├── auth.py                # /auth routes
│   │       ├── ingest.py              # /ingest routes (upload, replace, web crawl)
│   │       └── domains.py             # /domains routes
│   └── services/
│       ├── domain_service.py          # Domain business logic
│       └── ingestion/
│           ├── extractors.py          # Text + OCR extraction (PDF, DOCX, CSV)
│           ├── document_processor.py  # Celery-driven chunk/embed/store pipeline
│           ├── chunker.py             # LangChain text splitter wrapper
│           └── embedder.py            # Ollama embedding client
├── .env                               # Secret config (never commit)
├── .env.example                       # Safe template for teammates
├── requirements.txt
└── README.md
```

---

## Environment Setup

**1. Clone the repo and navigate to backend:**

```bash
cd backend
```

**2. Create and activate a conda environment:**

```bash
conda create -n paddleocr_env python=3.11
conda activate paddleocr_env
```

**3. Install PaddlePaddle first (required before other dependencies):**

GPU machine:
```bash
pip install paddlepaddle-gpu>=3.2.1
```

CPU machine:
```bash
pip install paddlepaddle>=3.2.1
```

> ⚠️ PaddlePaddle must be installed **before** `pip install -r requirements.txt`. Installing it after can cause version conflicts with PaddleOCR.

**4. Install remaining dependencies:**

```bash
pip install -r requirements.txt
```

**5. Create your `.env` file** by copying the example:

```bash
cp .env.example .env
```

Then fill in your values:

```
DATABASE_URL=postgresql://raguser:ragpass@localhost/ragdb
KEYCLOAK_URL=http://localhost:8080
KEYCLOAK_REALM=rag-realm
KEYCLOAK_CLIENT_ID=rag-backend
KEYCLOAK_CLIENT_SECRET=your-secret-from-keycloak
OLLAMA_BASE_URL=http://localhost:11434
EMBEDDING_MODEL=bge-m3:latest
EMBEDDING_DIMENSION=1024
QDRANT_HOST=localhost
QDRANT_PORT=6333
```

---

## Keycloak Setup

### Step 1 — Run Keycloak with Docker

```bash
docker run -d \
  --name keycloak \
  -p 8080:8080 \
  -e KEYCLOAK_ADMIN=admin \
  -e KEYCLOAK_ADMIN_PASSWORD=admin \
  quay.io/keycloak/keycloak:24.0.1 \
  start-dev
```

Wait ~30 seconds then open http://localhost:8080 and log in with `admin / admin`.

---

### Step 2 — Create a Realm

1. Top-left dropdown → **Create Realm**
2. Name: `rag-realm`
3. Click **Create**

---

### Step 3 — Create Roles

1. Left sidebar → **Realm roles** → **Create role**
2. Create these three roles one by one:
   - `admin`
   - `contributor`
   - `reader`

---

### Step 4 — Create a Client

1. Left sidebar → **Clients** → **Create client**
2. Client ID: `rag-backend`, Client type: `OpenID Connect` → **Next**
3. Turn **Client authentication** ON
4. Check both **Standard flow** and **Direct access grants** → **Next** → **Save**
5. Go to **Credentials** tab → copy the **Client secret** → paste into `.env` as `KEYCLOAK_CLIENT_SECRET`

---

### Step 5 — Fix Required Actions

> This step is critical — skip it and all logins will fail with "Account is not fully set up".

1. Left sidebar → **Authentication** → **Required actions** tab
2. Find any action with **Default action ON** (e.g. Verify Email, Update Profile)
3. Turn all **Default action** toggles **OFF**
4. Click **Save**

---

### Step 6 — Create Test Users

**Admin user:**

1. Left sidebar → **Users** → **Create new user**
2. Username: `testadmin`, Email: `testadmin@test.com`, Email verified: **ON** → **Create**
3. **Credentials** tab → **Set password** → `Test1234!` → Temporary: **OFF** → **Save password**
4. **Role mapping** tab → **Assign role** → select `admin`

**Reader user:**

Repeat the same steps with:
- Username: `testreader`
- Email: `testreader@test.com`
- Role: `reader`

---

### Step 7 — Increase Token Lifespan (for development)

1. **Realm settings** → **Tokens** tab
2. **Access Token Lifespan** → change from `5` to `30` minutes
3. **Save**

---

## Database Setup

### Option A — PostgreSQL via Docker (recommended)

```bash
docker run -d \
  --name ragdb \
  -p 5432:5432 \
  -e POSTGRES_USER=raguser \
  -e POSTGRES_PASSWORD=ragpass \
  -e POSTGRES_DB=ragdb \
  postgres:16
```

### Option B — Local PostgreSQL

Create a database called `ragdb` in your local PostgreSQL and update `DATABASE_URL` in `.env` with your credentials.

> Tables are created automatically on server startup via `Base.metadata.create_all()` — no manual SQL needed.

---

## Running the Stack Locally

Each command runs in a separate terminal. Make sure you are in the correct folder before running.

**Terminal 1 — Docker services**

From `infrastructure/docker/`:

```bash
docker compose -f docker-compose.dev.yml up
```

**Terminal 2 — FastAPI backend**

From `backend/`:

```bash
python -m uvicorn app.main:app --reload --port 8000
```

Swagger UI available at http://localhost:8000/docs

**Terminal 3 — Celery worker**

From `backend/`:

```bash
PROMETHEUS_WORKER_METRICS_PORT=9101 celery -A app.workers.celery_app worker --loglevel=debug -Q ingestion,extraction,evaluation --pool=solo
```

> `--pool=solo` is required on Windows.
> `PROMETHEUS_WORKER_METRICS_PORT=9101` is required — without it the worker defaults to port 9090, which collides with Prometheus's own port and breaks the Celery metrics dashboard.

**Terminal 4 — Ollama**

```bash
ollama serve
```

Pull models if not already downloaded:

```bash
ollama pull bge-m3:latest
ollama pull llama3.2:3b
```

**Terminal 5 — Frontend**

From `frontend/`:

```bash
npm install
npm run dev
```

Frontend available at http://localhost:5173
---

## OCR Support

The ingestion pipeline includes automatic OCR for scanned or image-heavy PDF pages using **PaddleOCR**.

### How it works

When a PDF is uploaded for ingestion, each page is processed as follows:

1. **Text extraction** — `pypdf` extracts any embedded text from the page.
2. **Image detection** — if the page contains embedded images, it is flagged for OCR.
3. **OCR** — `pymupdf` renders the page to a PNG at 200 DPI. PaddleOCR then reads the image and returns the recognized text lines.
4. **Both blocks are stored** — if a page has both embedded text and image content, two separate blocks are created: one with `source_type: pdf` and one with `source_type: pdf, block_type: ocr`. Both blocks go through the same chunking and embedding pipeline.

Pages with no images skip OCR entirely, keeping ingestion fast for standard text PDFs.

### OCR engine details

| Setting | Value |
|---|---|
| Library | PaddleOCR >= 3.4.0 |
| Language | Arabic (`lang="ar"`) |
| Device | GPU (`device="gpu"`) — falls back to CPU if GPU is unavailable |
| Render DPI | 200 |
| Engine lifecycle | Singleton — loaded once per Celery worker process and reused |

### Installing PaddlePaddle

PaddlePaddle must be installed **before** `pip install -r requirements.txt`.

GPU machine:
```bash
pip install paddlepaddle-gpu>=3.2.1
pip install -r requirements.txt
```

CPU machine:
```bash
pip install paddlepaddle>=3.2.1
pip install -r requirements.txt
```

> If you install PaddlePaddle after the other dependencies, you may hit version conflicts with PaddleOCR. The safest approach is always to install it first in a fresh environment.

### Switching OCR language

The engine is initialized in `backend/app/services/ingestion/extractors.py` inside `_get_ocr_engine()`. To change the language, update the `lang` parameter:

```python
_OCR_ENGINE = PaddleOCR(lang="ar", device="gpu")
```

Supported language codes: `ar` (Arabic), `en` (English), `fr` (French), and many others — see the [PaddleOCR documentation](https://paddlepaddle.github.io/PaddleOCR/latest/en/ppocr/blog/multi_languages.html) for the full list.

### Disabling GPU

If you are on a CPU-only machine, change `device="gpu"` to `device="cpu"` in `_get_ocr_engine()`. OCR will be significantly slower but fully functional.

---

## API Endpoints

### Auth

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/v1/auth/me` | Any role | Returns current user info |
| GET | `/api/v1/auth/admin-only` | Admin only | Role guard test endpoint |

### Domains

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/v1/domains/` | Admin | Create a new domain |
| GET | `/api/v1/domains/` | Any role | List all active domains |
| GET | `/api/v1/domains/my` | Any role | List domains the current user belongs to |
| GET | `/api/v1/domains/{id}` | Any role | Get a single domain by ID |
| PATCH | `/api/v1/domains/{id}/archive` | Admin | Archive or unarchive a domain |
| POST | `/api/v1/domains/{id}/members` | Admin | Add a user to a domain with a role |
| GET | `/api/v1/domains/{id}/members` | Any role | List members of a domain |

### Ingestion

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/v1/ingest/document` | Contributor | Upload a PDF, DOCX, or CSV for ingestion |
| POST | `/api/v1/ingest/replace` | Contributor | Replace an existing document with a new version |
| POST | `/api/v1/ingest/web` | Contributor | Queue a web crawl for a domain |
| GET | `/api/v1/ingest/status/{job_id}` | Any role | Check the status of an ingestion job |

#### Supported file types

| Extension | MIME type |
|---|---|
| `.pdf` | `application/pdf` |
| `.docx` | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` |
| `.csv` | `text/csv` |

#### Ingestion responses

| Status | Meaning |
|---|---|
| `200 IngestJobResponse` | Document queued successfully |
| `409 FileChangedResponse` | Same filename exists but content changed — confirm replace via `/ingest/replace` |
| `409 duplicate_document` | Exact same file already ingested — nothing to do |
| `400` | Unsupported file type |

---

## Postman Testing Guide

### Step 1 — Set up a Postman Collection

1. Create a new collection called `RAG Platform`
2. Go to the collection → **Variables** tab
3. Add a variable: `access_token` with an empty initial value

---

### Step 2 — Get a Token from Keycloak

Create a new request:

- Method: `POST`
- URL: `http://localhost:8080/realms/rag-realm/protocol/openid-connect/token`
- Body: `x-www-form-urlencoded`

| Key | Value |
|-----|-------|
| `client_id` | `rag-backend` |
| `client_secret` | your secret from Keycloak |
| `username` | `testadmin@test.com` |
| `password` | `Test1234!` |
| `grant_type` | `password` |

Go to the **Scripts** tab and add:

```javascript
var response = pm.response.json();
pm.collectionVariables.set("access_token", response.access_token);
```

Hit **Send** — you should get a JSON response with `access_token` inside. The script saves it automatically.

---

### Step 3 — Test Auth Endpoints

**GET /api/v1/auth/me**

- Method: `GET`
- URL: `http://localhost:8000/api/v1/auth/me`
- Authorization: Bearer Token → `{{access_token}}`

Expected response:
```json
{
    "keycloak_id": "some-uuid",
    "email": "testadmin@test.com",
    "role": "admin"
}
```

---

### Step 4 — Test Domain Endpoints

**Create a domain (admin only):**

- Method: `POST`
- URL: `http://localhost:8000/api/v1/domains/`
- Authorization: Bearer Token → `{{access_token}}`
- Body: raw JSON

```json
{
    "name": "HR",
    "description": "HR department documents"
}
```

**List all domains:**

- Method: `GET`
- URL: `http://localhost:8000/api/v1/domains/`
- Authorization: Bearer Token → `{{access_token}}`

**Archive a domain:**

- Method: `PATCH`
- URL: `http://localhost:8000/api/v1/domains/paste-domain-id-here/archive`
- Authorization: Bearer Token → `{{access_token}}`
- Body: raw JSON

```json
{
    "is_archived": true
}
```

**Add a member to a domain:**

- Method: `POST`
- URL: `http://localhost:8000/api/v1/domains/paste-domain-id-here/members`
- Authorization: Bearer Token → `{{access_token}}`
- Body: raw JSON

```json
{
    "user_id": "paste-keycloak-user-id-here",
    "role": "reader"
}
```

---

### Step 5 — Test Ingestion

**Upload a document:**

- Method: `POST`
- URL: `http://localhost:8000/api/v1/ingest/document`
- Authorization: Bearer Token → `{{access_token}}`
- Body: `form-data`

| Key | Type | Value |
|-----|------|-------|
| `domain_id` | Text | your-domain-uuid |
| `file` | File | select a PDF, DOCX, or CSV |

Expected response:
```json
{
    "job_id": "celery-task-uuid",
    "document_id": "document-uuid",
    "status": "pending",
    "message": "Document queued for processing."
}
```

**Check ingestion status:**

- Method: `GET`
- URL: `http://localhost:8000/api/v1/ingest/status/paste-job-id-here`
- Authorization: Bearer Token → `{{access_token}}`

Possible `status` values: `PENDING`, `STARTED`, `SUCCESS`, `FAILURE`, `RETRY`

---

### Step 6 — Test Role Enforcement

1. Go back to the get-token request
2. Change `username` to `testreader@test.com` and `password` to `Test1234!`
3. Hit Send — `{{access_token}}` now holds the reader token
4. Try `POST /api/v1/domains/` → should return `403 Forbidden`
5. Try `GET /api/v1/auth/me` → should return reader user info

---

### Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `Account is not fully set up` | Realm has default required actions | Authentication → Required actions → turn all Default action OFF |
| `Invalid token` | Token was copy-pasted and truncated | Use `{{access_token}}` variable instead of manual paste |
| `403 Forbidden` | User role not sufficient for this endpoint | Use admin token or check role assignment in Keycloak |
| `422 Unprocessable Entity` | Request body is wrong format | Make sure Body is set to raw → JSON |
| `Could not validate credentials` | Token expired | Re-run the get-token request to refresh |
| `paddleocr not found` | PaddlePaddle installed after requirements | Recreate the conda env, install PaddlePaddle first, then `pip install -r requirements.txt` |
| `OCR produces empty output` | PDF page has no detectable image content | Normal — pages without images skip OCR automatically |


# RBAC Isolation Test Suite

Automated pytest suite testing RBAC domain isolation across the hybrid RAG
pipeline, against a real Keycloak realm (not DEV_MODE).

## What this covers

| File | Tests |
|---|---|
| `test_cross_domain_isolation.py` | Zero-hit leakage checks across domains, at depth, and on direct doc fetch |
| `test_multi_role_union.py` | Multi-domain users get the union of access, not first-match-only, and role order doesn't matter |
| `test_shared_document_boundary.py` | Docs tagged to multiple domains don't over-expose domain tags or graph neighbors |
| `test_retrieval_path_parity.py` | BM25, vector, and graph paths each enforce filtering independently *before* RRF fusion |
| `test_token_staleness.py` | Revoked roles take effect promptly via session logout; documents the long-lived-token edge case |

## Before running

This suite is config-driven and currently full of `TODO` placeholders — it
will not pass as-is. You need to:

1. **`config.py`**
   - Confirm `KEYCLOAK_REALM`, `KEYCLOAK_CLIENT_ID` match your setup.
   - Confirm the realm role naming convention (`domain:hr` etc. is a guess —
     swap to whatever you actually use).
   - Fill in `ENDPOINTS` with real route paths. The three per-path debug
     routes (`query_bm25_only`, `query_vector_only`, `query_graph_only`)
     probably don't exist yet — see note below.
   - Fill in `TEST_USERS` with real Keycloak test accounts (create dedicated
     ones, don't reuse real users — `revocable_user` especially gets its
     roles mutated repeatedly).
   - Fill in `SEED_DOCS` with real doc_ids and unique probe terms. Probe
     terms should be tokens that exist in exactly one seed doc and nowhere
     else in the corpus, so a hit on that term is unambiguous evidence of
     that specific doc leaking.

2. **Admin credentials** — set via env vars rather than hardcoding:
   ```bash
   export KEYCLOAK_ADMIN_USER=admin
   export KEYCLOAK_ADMIN_PASSWORD=...
   export KEYCLOAK_BASE_URL=https://your-keycloak-host
   export RAG_API_BASE_URL=https://your-api-host
   ```
   The admin account needs `manage-users` on the target realm to grant/revoke
   roles and force session logout (used by the union and staleness tests).

3. **Seed data** — load `SEED_DOCS` into the actual corpus (Qdrant + AGE +
   whatever feeds BM25) via your normal ingestion path, tagged to the domains
   listed in config, *before* running the suite.

## On the per-path debug endpoints

`test_retrieval_path_parity.py` is the test most likely to catch a real bug
(filter clause drifting out of sync on one signal during a refactor), but it
needs a way to query BM25/vector/graph in isolation. If those routes don't
exist, the tests `skip` gracefully rather than failing — but that means this
risk is currently *unverifiable* through the API surface alone.

Worth considering: a debug-only route (gated behind an admin role or a
feature flag disabled in prod) that returns each signal's raw, filtered
candidate list pre-fusion. Even temporary, for this test pass.

## Running

```bash
pip install -r requirements.txt
pytest rbac_tests/ -v
```

Run a single file:
```bash
pytest rbac_tests/test_cross_domain_isolation.py -v
```

## Notes on design choices

- **Absence assertions, not rank assertions.** Every leak check asserts a
  forbidden doc/term doesn't appear at all, checked against both structured
  `doc_id` fields and the raw response text (in case a field gets renamed
  and a structured check alone would silently stop testing anything).
- **Session-scoped token caching** for stable users, but the staleness and
  role-union tests use a dedicated `revocable_user` and explicitly bust the
  cache after mutating roles, so they don't create flaky cross-test
  interference if run in parallel (`pytest -n auto`, if you add
  `pytest-xdist` later).
- **Cleanup at the end of mutating tests** restores the fixture user's
  baseline role so a failed run doesn't leave Keycloak in a state that
  breaks the next run.
