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
6. [Running the Server](#running-the-server)
7. [API Endpoints](#api-endpoints)
8. [Postman Testing Guide](#postman-testing-guide)

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
│   │       └── domains.py             # /domains routes
│   └── services/
│       └── domain_service.py          # Domain business logic
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
conda create -n rag python=3.11
conda activate rag
```

**3. Install dependencies:**

```bash
pip install -r requirements.txt
```

**4. Create your `.env` file** by copying the example:

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

## Running the Server

```bash
uvicorn app.main:app --reload
```

Server runs at http://localhost:8000

OpenAPI docs available at http://localhost:8000/docs

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

### Step 5 — Test Role Enforcement

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
celery -A app.workers.celery_app worker --loglevel=debug -Q ingestion,extraction,evaluation --pool=solo
```

> `--pool=solo` is required on Windows.

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