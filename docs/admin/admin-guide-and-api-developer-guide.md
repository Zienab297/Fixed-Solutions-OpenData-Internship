# Admin Guide and API Developer Guide

## Purpose

This document explains how administrators operate the RAG platform and how API developers integrate with the current FastAPI backend.

The source of truth for runtime behavior is the code and Docker configuration in this repository. Do not put real secrets in documentation, commits, screenshots, or shared tickets.

## Local URLs

| Component | URL |
| --- | --- |
| Frontend | `http://localhost:3000` |
| API health | `http://localhost:8000/health` |
| API OpenAPI docs | `http://localhost:8000/docs` |
| API metrics | `http://localhost:8000/metrics` |
| Prometheus | `http://localhost:9090` |
| Grafana | `http://localhost:3001` |
| Qdrant | `http://localhost:6333` |
| Ollama | `http://localhost:11434` |

## Runtime Configuration

Main compose file:

```text
infrastructure/docker/docker-compose.yml
```

Start command:

```powershell
docker compose -p rag-main -f infrastructure/docker/docker-compose.yml up -d --build
```

Production HTTPS overlay:

```powershell
docker compose -p rag-main `
  -f infrastructure/docker/docker-compose.yml `
  -f infrastructure/docker/docker-compose.tls.yml `
  up -d --build
```

Important settings:

| Variable | Meaning | Local default |
| --- | --- | --- |
| `DEV_MODE` | Use local JWT auth instead of full Keycloak flow | `true` in compose |
| `ADMIN_EMAIL` | Seeded system admin email | `admin@example.com` |
| `ADMIN_PASSWORD` | Seeded system admin password | `changeme123` |
| `SECRET_KEY` | JWT signing key for local auth | placeholder value |
| `EMBEDDING_MODEL` | Ollama embedding model | `bge-m3:latest` |
| `LOCAL_LLM_MODEL` | Ollama answer model | `llama3.2:3b` |
| `JUDGE_MODEL` | Ollama judge model | `llama3.2:3b` |
| `JUDGE_SCORE_THRESHOLD` | Score threshold for moderation flags | `0.7` |

Change all production secrets before launch.

## Admin Responsibilities

Admins are responsible for:

- creating domains
- creating users
- assigning users to the right domain role
- keeping source documents current
- reviewing flagged answers
- deleting incorrect or unauthorized documents
- monitoring uptime, latency, ingestion, and evaluation health
- rotating secrets when needed

## Role Model

| Role | Scope | Main permissions |
| --- | --- | --- |
| `reader` | Domain | Ask questions and view own answer evaluation |
| `contributor` | Domain | Reader permissions plus document upload |
| `domain_admin` | Domain | Contributor permissions plus users, quality, moderation, and document deletion for that domain |
| `admin` | System | Full system access, observability, and cross-domain administration |

The system admin is identified by `ADMIN_EMAIL`.

## Create and Manage Domains

Domains isolate documents, users, and access.

Domain fields include:

- `name`
- `description`
- `status`: `active` or `archived`
- `llm_route`: `local`, `api`, or `auto`
- `confidence_threshold`
- `chunk_size`
- `chunk_overlap`
- `supported_languages`

When a domain is created, the creator receives `domain_admin` access and the backend attempts to provision a Qdrant collection for that domain.

Use `llm_route=local` for sensitive domains unless there is an approved reason to call an external model provider.

## Create Users

Use **Create User** in the frontend.

System admins can create:

- `reader`
- `contributor`
- `domain_admin`

Domain admins can create users only inside their own domains and only with:

- `reader`
- `contributor`

Use temporary passwords carefully. Require password rotation in production identity management.

## Manage Documents

Documents are uploaded from the **Upload** page or through the ingestion API.

Supported source types through the current upload endpoint:

- PDF
- DOCX
- CSV

The backend stores:

- document metadata in Postgres
- chunks in Postgres
- vectors in Qdrant
- table rows for structured CSV lookup
- audit and evaluation records for query quality

If a document is wrong or unauthorized, delete it from the Quality domain detail page. This removes the document and its chunks, and attempts to remove matching Qdrant points.

## Quality and Moderation

The Judge LLM evaluates answers asynchronously.

Scores:

- faithfulness
- relevance
- completeness
- citation accuracy

Low scores create moderation items when they fall below the configured threshold.

Admin workflow:

1. Open **Quality**.
2. Review domain score summaries.
3. Open a domain detail view.
4. Inspect History, Files, and Flagged tabs.
5. Accept or reject flagged answers.
6. Delete or replace bad documents when the source material is the cause.

Audit logs and evaluation results are append-only evidence. Do not rewrite them to hide mistakes.

## Observability

Admins can open **Observability** in the frontend. It embeds the Grafana dashboard when Grafana allows embedding.

Prometheus scrapes:

- `api:8000/metrics`
- `worker:9090`
- `evaluation-worker:9090`
- `qdrant:6333/metrics`

Use the dashboard for:

- API availability
- request latency
- query latency
- worker health
- evaluation latency
- Qdrant metrics

## API Developer Guide

Base URL:

```text
http://localhost:8000/api/v1
```

Interactive API docs:

```text
http://localhost:8000/docs
```

Authentication uses Bearer tokens.

In local Docker mode, `DEV_MODE=true` uses local JWT login. When `DEV_MODE=false`, login uses Keycloak and the user must also exist locally.

### Login

Endpoint:

```text
POST /auth/token
```

Content type:

```text
application/x-www-form-urlencoded
```

PowerShell example:

```powershell
$login = Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8000/api/v1/auth/token" `
  -Body @{ username = "admin@example.com"; password = "changeme123" }

$token = $login.access_token
$headers = @{ Authorization = "Bearer $token" }
```

### Current User

```text
GET /auth/me
```

Returns the authenticated user's id, Keycloak id, email, user pool, top role, and creation time.

### Users

```text
POST /auth/users
```

Body:

```json
{
  "email": "user@example.com",
  "password": "temporary-password",
  "role": "reader",
  "domain_id": "00000000-0000-0000-0000-000000000000"
}
```

Requires system admin or domain admin permissions.

### Domains

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/domains/` | Create a domain |
| `GET` | `/domains/` | List active domains |
| `GET` | `/domains/?include_archived=true` | List active and archived domains |
| `GET` | `/domains/my` | List current user's memberships |
| `GET` | `/domains/{domain_id}` | Get one domain |
| `PATCH` | `/domains/{domain_id}/archive` | Archive or restore a domain |
| `POST` | `/domains/{domain_id}/members` | Add a member |
| `GET` | `/domains/{domain_id}/members` | List domain members |

Create domain body:

```json
{
  "name": "Policies",
  "description": "Internal policy documents",
  "llm_route": "local",
  "confidence_threshold": 0.7,
  "chunk_size": 512,
  "chunk_overlap": 64,
  "supported_languages": ["en", "ar"]
}
```

Archive body:

```json
{
  "archived": true
}
```

Add member body:

```json
{
  "user_id": "00000000-0000-0000-0000-000000000000",
  "role": "contributor"
}
```

### Ingestion

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/ingest/document` | Upload PDF, DOCX, or CSV |
| `POST` | `/ingest/replace` | Replace a changed document after confirmation |
| `POST` | `/ingest/web` | Queue a whitelisted web crawl |
| `GET` | `/ingest/status/{job_id}` | Check Celery job status |

Upload example:

```powershell
$form = @{
  domain_id = "00000000-0000-0000-0000-000000000000"
  file = Get-Item "C:\path\document.pdf"
}

Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8000/api/v1/ingest/document" `
  -Headers $headers `
  -Form $form
```

Possible upload conflicts:

- `duplicate_document`: exact same file already exists in the domain
- `file_changed`: same filename but different content; call `/ingest/replace` only after confirmation

### Query

Endpoint:

```text
POST /query
```

Body:

```json
{
  "query": "What does the policy say about leave approval?",
  "domain_ids": ["00000000-0000-0000-0000-000000000000"],
  "domain_routes": {},
  "context": [],
  "top_k": 5
}
```

Response includes:

- `query_id`
- `answer`
- `llm_route`
- `language_detected`
- `citations`
- `confidence_score`
- `signals_used`
- `evaluation`

The judge evaluation is usually asynchronous. Use `GET /evaluate/{query_id}` to poll for completion.

### Evaluation and Quality

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/evaluate/{query_id}` | Get judge status and scores for a query |
| `GET` | `/evaluate/quality/summary` | Get domain quality summaries |
| `GET` | `/evaluate/quality/summary?domain_id={domain_id}` | Filter summary by domain |
| `GET` | `/evaluate/quality/domains/{domain_id}` | Get domain history, files, and flagged items |
| `DELETE` | `/evaluate/quality/domains/{domain_id}/documents/{document_id}` | Delete a domain document |
| `GET` | `/evaluate/moderation?status_filter=pending` | List moderation items |
| `PATCH` | `/evaluate/moderation/{item_id}` | Update moderation item status |

Moderation update body:

```json
{
  "status": "accepted",
  "reviewer_rationale": "The cited context supports the answer."
}
```

Allowed moderation statuses:

- `pending`
- `accepted`
- `rejected`

### Health and Metrics

These endpoints are outside `/api/v1`:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | API health check |
| `GET` | `/metrics` | Prometheus metrics |

## Common Status Codes

| Status | Meaning |
| --- | --- |
| `200` | Request succeeded |
| `201` | User created |
| `400` | Invalid request or unsupported role/file/status |
| `401` | Missing or invalid authentication |
| `403` | Authenticated but insufficient domain permission |
| `404` | Domain, document, moderation item, or query not found |
| `409` | Duplicate or changed document upload conflict |
| `504` | Local LLM generation timed out |

## Data Model Summary

Core tables live in the `rag` Postgres schema.

| Table | Purpose |
| --- | --- |
| `users` | Local user records |
| `domains` | Domain metadata and routing settings |
| `domain_roles` | User access per domain |
| `documents` | Uploaded or crawled source documents |
| `chunks` | Embedded document chunks |
| `table_rows` | Structured rows extracted from CSV files |
| `audit_logs` | Append-only query records |
| `evaluation_results` | Append-only Judge LLM scores |
| `moderation_queue` | Flagged answers awaiting admin review |
| `crawl_configs` | Web crawl allowlists and schedules |

## Production Readiness Notes

- Replace local default passwords.
- Use a long random `SECRET_KEY`.
- Keep real `.env` files out of Git.
- Use HTTPS through the TLS compose overlay or deployment platform.
- Restrict external LLM use to approved domains.
- Confirm Grafana and Prometheus are not exposed publicly without authentication.
- Verify backups for Postgres and Qdrant before go-live.

## Acceptance Checklist

- Admin can start the stack and verify health.
- Admin can create domains and users.
- Domain admin can upload, review, moderate, and delete domain documents.
- API developer can authenticate and call core endpoints.
- Production secrets and external exposure risks are documented.