# Post-MVP Backlog

## Purpose

This document captures features and improvements that were deliberately deferred from the MVP. Every item maps to a real gap identified in the current codebase. Items are **not committed** — they must be sized and moved to the sprint board before work starts.

> **Effort key:** S = 1–2 days · M = 3–5 days · L = 1–2 weeks · XL = 2+ weeks

---

## 1. Retrieval Quality

Current implementation: `RetrievalPipeline` in `backend/app/services/retrieval/pipeline.py` runs Vector (Qdrant) + BM25 (PostgreSQL) + Graph (Apache AGE), fuses with RRF, applies lexical rerank.

| ID | Item | Priority | Effort | Current state |
|----|------|----------|--------|---------------|
| RQ-01 | Add a cross-encoder re-ranker step after RRF fusion to improve faithfulness | High | M | Currently only RRF + lexical boost — no cross-encoder pass |
| RQ-02 | Multi-turn / conversational context — carry chat history window across queries | High | L | `query.py` is stateless per request; no history passed to LLM |
| RQ-03 | Citation sentence grounding — link each sentence in the answer to a specific chunk | Medium | M | Citations are chunk-level (`_build_citations`), not sentence-level |
| RQ-04 | Improve Arabic retrieval — evaluate `bge-m3:latest` accuracy on Arabic queries and switch to an Arabic-optimised embedding model if needed | High | M | `bge-m3` is multilingual; `OCR_LANG=ar` is set but embedding quality for Arabic not validated |
| RQ-05 | Add HyDE (Hypothetical Document Embeddings) for sparse or ambiguous queries | Low | M | Not in `pipeline.py`; could improve recall on short queries |

---

## 2. Document Ingestion

Current implementation: `document_processor.py` → `extractors.py` (PDF via `pypdf` + `pymupdf` + OCR, DOCX via `python-docx`, CSV). OCR via `ocr_engines.py`. Chunking in `chunker.py`. Embedding via `embedder.py` (Ollama `bge-m3:latest`). Celery `ingestion` and `extraction` queues.

| ID | Item | Priority | Effort | Current state |
|----|------|----------|--------|---------------|
| IN-01 | Add XLSX support — DB model `chk_document_source_type` already includes `xlsx` but `extractors.py` raises `ValueError` for it | High | S | `extract_document()` does not handle `xlsx` despite the DB constraint allowing it |
| IN-02 | Add webpage/URL ingestion — `source_type='webpage'` is in the DB constraint and `CrawlConfig` model exists but `web_crawler.py` is an empty stub | Medium | L | `services/ingestion/web_crawler.py` is 37 bytes (stub only) |
| IN-03 | Document versioning — re-uploading a changed file currently hits the `uq_document_hash_domain` unique constraint and fails; implement replace-with-history workflow | High | L | Hash check in `Document.hash_content()` enforces uniqueness; no versioning path exists |
| IN-04 | Batch ingestion endpoint — accept multiple files in one `POST /api/v1/ingest/document` call | Low | S | Current endpoint is single-file only |
| IN-05 | Semantic chunking — replace fixed-size chunking in `chunker.py` with boundary-aware chunking | Medium | M | `chunker.py` uses `chunk_size=512` / `chunk_overlap=64` from domain config |

---

## 3. LLM Routing

Current implementation: `backend/app/services/llm/router.py` routes based on domain `llm_route` field (`local`, `api`, `auto`). Local = Ollama (`llama3.2:3b`). External = configured via `EXTERNAL_LLM_*` env vars (`external_llm.py`). Language detection in `language_detector.py`.

| ID | Item | Priority | Effort | Current state |
|----|------|----------|--------|---------------|
| LM-01 | Fallback routing — if Ollama endpoint is unreachable, automatically switch to external LLM and vice versa | High | M | `router.py` does not implement fallback; a failed Ollama call results in an error response |
| LM-02 | Streaming response tokens to the frontend via SSE | High | L | `query.py` returns the full answer at once; no streaming |
| LM-03 | Per-domain prompt template — let `domain_admin` set a custom system prompt stored in the `Domain` model | Medium | M | Prompt is hardcoded in `router.py`; `Domain` model has no `system_prompt` column |
| LM-04 | Validate that `GENERATION_MODEL` env var (set in `.env`) is actually used — currently `LOCAL_LLM_MODEL` is used in compose but `GENERATION_MODEL` also exists | Low | S | Minor config inconsistency between `.env.example` and compose env |

---

## 4. Evaluation and Moderation

Current implementation: `judge.py` scores answers on `faithfulness`, `relevance`, `completeness`, `citation_accuracy`. Scores stored in `evaluation_results`. Flagged items go to `moderation_queue`. `audit_writer.py` is a stub.

| ID | Item | Priority | Effort | Current state |
|----|------|----------|--------|---------------|
| EV-01 | Complete `audit_writer.py` — currently a 37-byte stub; write query + answer + route to `audit_logs` | High | S | `audit_writer.py` is empty; `audit_logs` is written to directly in `query.py` — consolidate |
| EV-02 | Complete `regression.py` — currently a 37-byte stub; implement regression test runner against `golden_dataset` | Medium | L | `golden_dataset` table exists in DB model but `regression.py` is empty |
| EV-03 | User feedback — thumbs up/down on individual answers stored in `audit_logs` or a new `feedback` table | High | S | No feedback mechanism exists; would feed into moderation priority |
| EV-04 | Per-domain configurable judge threshold — `JUDGE_SCORE_THRESHOLD` is a global env var; move it to `Domain.confidence_threshold` (column already exists) | Medium | M | `confidence_threshold` column is in the `Domain` model but judge uses the global env var |
| EV-05 | Domain quality trend chart — score over time per domain for the Quality dashboard | Medium | M | `evaluation_results` stores timestamps; no trend aggregation endpoint exists yet |

---

## 5. RBAC and User Management

Current implementation: JWT auth in `auth.py`. Roles: `reader`, `contributor`, `domain_admin`, `admin` in `domain_roles`. `DEV_MODE=true` skips Keycloak and uses local password hash. Keycloak configured but optional.

| ID | Item | Priority | Effort | Current state |
|----|------|----------|--------|---------------|
| UM-01 | Password reset flow for dev-mode users (`user_pool='internal'`) | High | M | No reset endpoint exists; `password_hash` column exists but only set on seed |
| UM-02 | Admin UI for creating and assigning domain roles — currently done via API calls only | Medium | M | No frontend page for user management |
| UM-03 | API key management UI — `APIKey` model exists with `rate_limit_per_day`, but no UI for creating/revoking keys | Low | M | API key endpoint exists in backend; not surfaced in frontend |
| UM-04 | Enforce `rate_limit_per_day` on `APIKey` — column exists in model but rate limiting is not implemented in middleware | Medium | M | Column `rate_limit_per_day` on `api_keys` table; no enforcement code found |

---

## 6. Observability and Operations

Current implementation: `prometheus_fastapi_instrumentator` on `/metrics`. Custom metrics in `app/core/metrics.py` (`RETRIEVAL_SIGNAL_LATENCY`, `RETRIEVAL_HIT_RATE`, `GRAPH_QUERY_LATENCY`). JSON logging via `logging_config.py`. Grafana provisioned from `infrastructure/docker/grafana/`. Workers expose metrics on port 9090 via `workers/observability.py`.

| ID | Item | Priority | Effort | Current state |
|----|------|----------|--------|---------------|
| OB-01 | Complete Grafana dashboard — provisioning directory exists but dashboard JSON needs panels for retrieval signals, judge queue depth, eval latency, and ingestion throughput | High | M | Directory exists at `infrastructure/docker/grafana/dashboards/`; content unknown |
| OB-02 | Add judge queue depth metric — Celery `evaluation` queue depth is not currently tracked as a Prometheus metric | Medium | S | `workers/observability.py` exists; add Celery queue depth gauge |
| OB-03 | Add alert rules — no alerting configured; at minimum alert on API container down, Celery worker inactive, Qdrant unreachable | High | M | Prometheus is running but no `rules.yml` exists |
| OB-04 | Distributed tracing (OpenTelemetry) across API → Celery worker → LLM call | Low | L | Not implemented |

---

## 7. NER Microservice

Current implementation: `services/ner/` is a separate microservice. `NERService` in `backend/app/services/retrieval/ner.py` calls it via `NER_SERVICE_URL`. Integrated into `RetrievalPipeline` for entity extraction before graph search.

| ID | Item | Priority | Effort | Current state |
|----|------|----------|--------|---------------|
| NER-01 | Add NER service to `docker-compose.yml` — currently missing; must be started manually | High | S | `NER_SERVICE_URL=http://localhost:8001` in `.env.example` but no compose service definition |
| NER-02 | Add health check for NER service — pipeline silently returns empty entities if NER is down | Medium | S | `RetrievalPipeline._safe()` swallows NER errors; should surface as a degraded signal warning |

---

## 8. Security

| ID | Item | Priority | Effort | Current state |
|----|------|----------|--------|---------------|
| SEC-01 | Restrict CORS — `allow_origins=["*"]` is hardcoded in `main.py`; must be restricted to the actual frontend origin before production | High | S | `app.add_middleware(CORSMiddleware, allow_origins=["*"])` in `main.py` |
| SEC-02 | GDPR / PII review — `audit_logs.query_text` stores the full user query; assess if this constitutes personal data | High | M | `query_text` column in `audit_logs`; no PII scrubbing |
| SEC-03 | Data retention policy — no auto-deletion of `audit_logs` older than N days | Medium | M | Table is append-only by design; no retention job exists |
| SEC-04 | External penetration test before loading sensitive production data | High | XL | Not done |

---

## 9. Frontend and UX

Frontend is Vite + TypeScript + Tailwind CSS (`frontend/src/`).

| ID | Item | Priority | Effort | Current state |
|----|------|----------|--------|---------------|
| FE-01 | Add conversation history sidebar — current chat is stateless per page load | High | M | No history stored client-side or fetched from `audit_logs` |
| FE-02 | Show retrieval signals used in answer (`vector`, `bm25`, `graph`) — returned in query response but not displayed | Medium | S | `signals_used` is in the API response; UI does not render it |
| FE-03 | Mobile responsive layout | Low | L | Designed for desktop; Tailwind responsive classes likely partial |
| FE-04 | Accessibility audit (WCAG 2.1 AA) | Low | M | Not done |

---

## 10. Technical Debt

| ID | Item | Area | Effort |
|----|------|------|--------|
| TD-01 | `docs/operations/runbooks-and-on-call-playbook.md` is an empty file (0 bytes) — write actual runbook content | Operations | M |
| TD-02 | `services/ingestion/web_crawler.py` is a 37-byte stub — implement or remove it | Ingestion | L |
| TD-03 | `services/evaluation/audit_writer.py` is a 37-byte stub — implement audit write logic | Evaluation | S |
| TD-04 | `services/evaluation/regression.py` is a 37-byte stub — implement regression runner | Evaluation | L |
| TD-05 | `GENERATION_MODEL` env var in `.env.example` is never used in `docker-compose.yml` — reconcile or remove | Config | S |
| TD-06 | `print()` debug statements in `pipeline.py` (`DEBUG NER entities`, `DEBUG domain_names`) — replace with `logger.debug()` | Retrieval | S |
| TD-07 | NER microservice has no entry in `docker-compose.yml` — add it or document manual start | Infrastructure | S |
| TD-08 | Add ADRs for: Qdrant as vector DB, `bge-m3:latest` as embedding model, Redis/Celery as task queue | ADR | M |

---

## How to Use This Backlog

1. **Priority** here is advisory — final priority is decided in sprint planning.
2. **Effort** must be re-estimated by the implementing engineer before a card enters a sprint.
3. **New items** should be added here first, then discussed in the next backlog refinement session.
4. Moving an item to the sprint board requires a one-paragraph scope definition on the card.

---

*Last updated: 2026-06-29*
