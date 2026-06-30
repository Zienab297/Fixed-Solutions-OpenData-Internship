# GO-Live Checklist

## Purpose

This checklist must be completed before the RAG platform is promoted to production. Every item maps to something that actually exists in this codebase. Do not promote to production if any item is blocked or skipped without a documented waiver.

---

## 1. Infrastructure — Docker Compose Services

All services are defined in `infrastructure/docker/docker-compose.yml`.

| # | Service | Check | Status |
|---|---------|-------|--------|
| 1.1 | `postgres` (postgres:16) — starts healthy, `pg_isready` passes | Run `docker compose ps` and confirm `healthy` | ☐ |
| 1.2 | `qdrant` (qdrant/qdrant:latest) — vector DB reachable on port 6333 | `curl http://localhost:6333/healthz` returns OK | ☐ |
| 1.3 | `redis` (redis:7-alpine) — broker and result backend reachable on port 6379 | `redis-cli -a $REDIS_PASSWORD ping` returns PONG | ☐ |
| 1.4 | `ollama` — pulls `$LOCAL_LLM_MODEL` (default `llama3.2:3b`) and `$EMBEDDING_MODEL` (default `bge-m3:latest`) on startup | Check container logs for pull success | ☐ |
| 1.5 | `judge-ollama` — separate Ollama instance for judge LLM, pulls `$JUDGE_MODEL` (default `llama3.2:3b`) | Check container logs for pull success | ☐ |
| 1.6 | `api` (FastAPI) — starts, health check passes on `GET /health` | `curl http://localhost:8000/health` returns `{"status":"healthy"}` | ☐ |
| 1.7 | `worker` (Celery, queues: `ingestion,extraction,celery`) — running and consuming | `celery -A app.workers.celery_app inspect active` | ☐ |
| 1.8 | `evaluation-worker` (Celery, queue: `evaluation`) — running and consuming | `celery -A app.workers.celery_app inspect active` | ☐ |
| 1.9 | `frontend` — built, served via nginx on port 3000 | `curl http://localhost:3000` returns HTML | ☐ |
| 1.10 | `prometheus` — scraping `api:8000/metrics`, `worker:9090`, `evaluation-worker:9090` | Prometheus UI shows all targets UP | ☐ |
| 1.11 | `grafana` — connected to Prometheus datasource, dashboards auto-provisioned | Open `http://localhost:3001`, confirm dashboard loads | ☐ |

---

## 2. Environment Variables and Secrets

All variables come from `.env` (copy of `.env.production.example` for production). Never use `.env.example` defaults in production.

| # | Variable | Check | Status |
|---|----------|-------|--------|
| 2.1 | `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` — set to production values (not `ragdb`/`raguser`/`ragpassword`) | Confirm `.env` values | ☐ |
| 2.2 | `DATABASE_URL` — uses `postgresql+asyncpg://` scheme, points to `postgres` container | Matches compose service name | ☐ |
| 2.3 | `REDIS_PASSWORD` — changed from default `1234` | Confirm `.env` value | ☐ |
| 2.4 | `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` — use `REDIS_PASSWORD` from above | Matches compose env | ☐ |
| 2.5 | `SECRET_KEY` — changed from `change-me-in-production-use-a-long-random-string` to a real random secret | At least 32 random characters | ☐ |
| 2.6 | `ADMIN_PASSWORD` — changed from default `changeme123` | Confirm `.env` value | ☐ |
| 2.7 | `DEV_MODE=false` — Keycloak is active, not skipped | Confirm `.env` has `DEV_MODE=false` | ☐ |
| 2.8 | `KEYCLOAK_URL`, `KEYCLOAK_REALM`, `KEYCLOAK_CLIENT_ID`, `KEYCLOAK_CLIENT_SECRET` — set to production Keycloak | Confirm `.env` values | ☐ |
| 2.9 | `QDRANT_HOST=qdrant`, `QDRANT_PORT=6333` — match compose service | Confirmed | ☐ |
| 2.10 | `OLLAMA_BASE_URL`, `LOCAL_LLM_BASE_URL` — point to `ollama` container | `http://ollama:11434` | ☐ |
| 2.11 | `JUDGE_LLM_BASE_URL` — points to `judge-ollama` container | `http://judge-ollama:11434` | ☐ |
| 2.12 | `EMBEDDING_MODEL=bge-m3:latest`, `EMBEDDING_DIMENSION=1024` — match what was used during ingestion | Confirm model was pulled by Ollama | ☐ |
| 2.13 | `JUDGE_SCORE_THRESHOLD` — set to desired threshold (default `0.7`) | Confirm for production domain quality bar | ☐ |
| 2.14 | `JUDGE_ENABLED=true` — evaluation worker will score answers | Confirmed | ☐ |
| 2.15 | `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD` — changed from default `admin/admin` | Confirm `.env` values | ☐ |
| 2.16 | `NER_SERVICE_URL` — points to running NER microservice (`services/ner`) | `http://ner-service:8001` or equivalent | ☐ |
| 2.17 | `OCR_LANG` — set to correct language(s) for production documents (e.g. `ar` for Arabic) | Confirm `.env` value | ☐ |
| 2.18 | `OCR_DEVICE` — set to `gpu` if GPU is available, otherwise `cpu` | Match actual hardware | ☐ |

---

## 3. Database and Schema

Schema is in the `rag` PostgreSQL schema. Tables are created on startup by `app/main.py` via SQLAlchemy `create_all`.

| # | Item | Check | Status |
|---|------|-------|--------|
| 3.1 | Schema `rag` exists in PostgreSQL — created on startup | Startup logs show `Creating database schema 'rag'` | ☐ |
| 3.2 | All tables exist: `users`, `domains`, `domain_roles`, `api_keys`, `documents`, `chunks`, `table_rows`, `audit_logs`, `evaluation_results`, `golden_dataset`, `moderation_queue`, `crawl_configs` | `\dt rag.*` in psql | ☐ |
| 3.3 | Lightweight migrations ran: `query_text`, `answer_text` columns added to `audit_logs`; indexes `idx_audit_query_id`, `idx_audit_domains_queried` created | Startup logs show migration lines | ☐ |
| 3.4 | Seed admin user created — `seed_admin()` ran on startup | Log shows `Seeding system admin...` | ☐ |
| 3.5 | `password_hash` column exists on `rag.users` (required even when `DEV_MODE=false`) | `ALTER TABLE rag.users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255)` ran | ☐ |
| 3.6 | Qdrant collection(s) initialized for each active domain | At least one collection visible in Qdrant UI at `http://localhost:6333/dashboard` | ☐ |
| 3.7 | PostgreSQL data volume (`postgres_data`) is on a persistent host path or backup-enabled volume | Confirmed in compose volumes config | ☐ |

---

## 4. API Endpoints — Functional Verification

All endpoints are prefixed `/api/v1`. Defined in `backend/app/api/v1/endpoints/`.

| # | Endpoint | Method | Expected result | Status |
|---|----------|--------|-----------------|--------|
| 4.1 | `/health` | GET | `{"status":"healthy"}` | ☐ |
| 4.2 | `/metrics` | GET | Prometheus text exposition (HTTP metrics from `prometheus-fastapi-instrumentator`) | ☐ |
| 4.3 | `/api/v1/auth/login` | POST | Returns JWT token for valid credentials | ☐ |
| 4.4 | `/api/v1/domains` | GET | Returns domain list for authenticated user | ☐ |
| 4.5 | `/api/v1/ingest/document` | POST | Accepts PDF/DOCX/CSV, returns `job_id`, status becomes `completed` | ☐ |
| 4.6 | `/api/v1/query` | POST | Returns answer, `llm_route` (`local`/`api`/`auto`), detected language, citation list | ☐ |
| 4.7 | `/api/v1/evaluate/*` | GET/POST | Quality dashboard data loads — domain scores, flagged counts, moderation queue | ☐ |
| 4.8 | `/api/v1/audit` | GET | Audit log entries visible for admin | ☐ |

---

## 5. Ingestion Pipeline — End-to-End

Code path: `ingest.py` endpoint → Celery `ingestion` queue → `tasks.py` → `document_processor.py` → `extractors.py` + `ocr_engines.py` + `chunker.py` + `embedder.py` → Qdrant + PostgreSQL.

| # | Item | Check | Status |
|---|------|-------|--------|
| 5.1 | Upload a PDF → job reaches `completed` status | Check `ingest_status` on `rag.documents` | ☐ |
| 5.2 | Upload a DOCX → chunks appear in `rag.chunks` and Qdrant | Confirm chunk count > 0 | ☐ |
| 5.3 | Upload a CSV → `table_rows` populated in `rag.table_rows` | Check `rag.table_rows` for rows | ☐ |
| 5.4 | Duplicate file (same SHA-256 hash, same domain) → rejected with duplicate error | `uq_document_hash_domain` constraint enforced | ☐ |
| 5.5 | PDF with images → OCR runs (`ocr_engines.py`), `ocr_used=true` on document | Check `rag.documents.ocr_used` | ☐ |
| 5.6 | Embeddings use `bge-m3:latest` at dimension 1024 via Ollama | Confirm `embedding_model` on `rag.chunks` | ☐ |
| 5.7 | Celery worker metrics exposed on port 9090, scraped by Prometheus | `PROMETHEUS_WORKER_METRICS_PORT=9090` confirmed | ☐ |

---

## 6. Retrieval Pipeline — Functional Verification

Code path: `query.py` → `RetrievalPipeline` → Vector (Qdrant) + BM25 (PostgreSQL) + Graph (Apache AGE) → RRF fusion → LLM router → answer.

| # | Item | Check | Status |
|---|------|-------|--------|
| 6.1 | Vector search returns chunks from Qdrant for a test query in an ingested domain | Answer contains citations | ☐ |
| 6.2 | BM25 search (`bm25_search.py`) runs against PostgreSQL `rag.chunks` | Signals list in response includes `bm25` | ☐ |
| 6.3 | RRF fusion (`rrf.py`) combines vector and BM25 results | `signals_used` in response shows both | ☐ |
| 6.4 | NER (`services/ner`) extracts entities and graph search (`graph_search.py`) runs when entities found | Graph signal appears in response when applicable | ☐ |
| 6.5 | Language detection (`lang_detect.py`) correctly identifies query language (Arabic / English) | `detected_language` field in response is correct | ☐ |
| 6.6 | LLM routing: domain with `llm_route=local` uses Ollama; domain with `llm_route=api` uses external LLM | Verify `llm_route` field in query response | ☐ |
| 6.7 | `MOCK_LLM_RESPONSES=false` in production — real LLM is called | Confirmed in compose env | ☐ |

---

## 7. Evaluation and Moderation

Code path: `evaluate.py` endpoint → Celery `evaluation` queue → `judge.py` → scores stored in `evaluation_results` → moderation flagging.

| # | Item | Check | Status |
|---|------|-------|--------|
| 7.1 | After a query, `evaluation-worker` picks up the evaluation task | Celery logs show `evaluation` queue task consumed | ☐ |
| 7.2 | Judge LLM (`judge-ollama`, model `$JUDGE_MODEL`) scores: `faithfulness`, `relevance`, `completeness`, `citation_accuracy` | Scores appear in `rag.evaluation_results` | ☐ |
| 7.3 | Answers below `JUDGE_SCORE_THRESHOLD` are flagged and inserted into `rag.moderation_queue` | `flagged=true` row appears in `moderation_queue` | ☐ |
| 7.4 | Admin can accept or reject a moderation item via the evaluate endpoint | Status on `moderation_queue` row changes to `accepted`/`rejected` | ☐ |
| 7.5 | `audit_logs` records are append-only — no update/delete in `audit_writer.py` | Confirmed in code | ☐ |

---

## 8. RBAC and Security

Roles are `reader`, `contributor`, `domain_admin`, `admin`. Enforced in `auth.py` and `dependencies/`.

| # | Item | Check | Status |
|---|------|-------|--------|
| 8.1 | `DEV_MODE=false` — JWT is verified against Keycloak JWKS, not a dev bypass | Confirm `.env` | ☐ |
| 8.2 | `reader` role — can query, cannot upload, cannot see quality/admin pages | Test with a reader-scoped token | ☐ |
| 8.3 | `contributor` role — can upload documents to their assigned domain | Test file upload | ☐ |
| 8.4 | `domain_admin` role — can access quality dashboard and moderate for their domain only | Test cross-domain access is blocked | ☐ |
| 8.5 | `admin` role — full access to all domains, users, observability | Test admin endpoints | ☐ |
| 8.6 | Domain-scoped RBAC — user in Domain A cannot query or see documents from Domain B | Test with two separate domains | ☐ |
| 8.7 | `CORS` — `allow_origins=["*"]` in `main.py` — restrict to known origin(s) before production | Update `main.py` or configure via reverse proxy | ☐ |
| 8.8 | Secrets (`SECRET_KEY`, `ADMIN_PASSWORD`, passwords) are not logged anywhere | Review `logging_config.py` and log output | ☐ |

---

## 9. Observability

Metrics are exposed by `prometheus_fastapi_instrumentator` on `/metrics` and by custom metrics in `app/core/metrics.py`. Workers expose metrics on port 9090. Grafana dashboards are auto-provisioned from `infrastructure/docker/grafana/`.

| # | Item | Check | Status |
|---|------|-------|--------|
| 9.1 | Prometheus targets: `api:8000`, `worker:9101`, `evaluation-worker:9102`, `qdrant:6333` — all UP | Prometheus targets page | ☐ |
| 9.2 | `RETRIEVAL_SIGNAL_LATENCY` metric visible — latency per signal (vector, bm25, graph) | `PromQL: retrieval_signal_latency_seconds_bucket` | ☐ |
| 9.3 | `RETRIEVAL_HIT_RATE` metric visible — hit/miss per signal | `PromQL: retrieval_hit_rate_total` | ☐ |
| 9.4 | `GRAPH_QUERY_LATENCY` metric visible | `PromQL: graph_query_latency_seconds_bucket` | ☐ |
| 9.5 | Grafana dashboard loads and shows data from Prometheus | Open `http://localhost:3001` | ☐ |
| 9.6 | JSON structured logging active — `configure_json_logging(service_name="rag-api")` | Log output is JSON, not plain text | ☐ |

---

## 10. Frontend Verification

Frontend is a Vite + TypeScript app served via nginx on port 3000.

| # | Page / feature | Check | Status |
|---|----------------|-------|--------|
| 10.1 | Login screen loads at `http://localhost:3000` | No console errors | ☐ |
| 10.2 | Login with admin credentials works and redirects to dashboard | JWT stored, user sees correct role-based nav | ☐ |
| 10.3 | Logout clears session | Back button does not restore session | ☐ |
| 10.4 | Chat page — select a domain, submit a query, receive answer with route and language | End-to-end test | ☐ |
| 10.5 | Upload page — upload a PDF, copy job id, track status to `completed` | End-to-end test | ☐ |
| 10.6 | Quality page (admin/domain_admin) — domain scores, flagged counts, query history visible | Loads without errors | ☐ |
| 10.7 | Files tab (domain_admin) — shows ingested documents with `ingest_status`, `chunk_count` | Loads without errors | ☐ |
| 10.8 | Moderation review — accept/reject actions work | Status updates in UI | ☐ |

---

## 11. Final Sign-Off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Tech Lead | | | |
| DevOps | | | |
| QA | | | |
| Product Owner | | | |

---

## Waivers and Deferred Items

> Any item skipped must be documented here with a reason and a target date.

| Item # | Reason | Owner | Target Date |
|--------|--------|-------|-------------|
| | | | |

---

*Last updated: 2026-06-29*
