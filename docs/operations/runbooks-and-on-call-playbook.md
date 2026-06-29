# Runbooks and On-Call Playbook

## Purpose

This document is the first-response guide for operating the RAG platform. It covers the local or single-host Docker deployment used by this project, the expected service map, first checks, common incidents, and handoff expectations.

Use this together with:

- `docs/security/tls-and-secrets-management.md`
- `docs/governance/responsible-use-policy.md`
- `docs/architecture/README.md`

## Service Map

The main Docker stack is defined in `infrastructure/docker/docker-compose.yml`.

| Service | Purpose | Local URL or port |
| --- | --- | --- |
| `frontend` | React UI served through Nginx | `http://localhost:3000` |
| `api` | FastAPI backend | `http://localhost:8000` |
| `postgres` | Relational data in schema `rag` | `127.0.0.1:5432` |
| `redis` | Celery broker and result backend | `127.0.0.1:6379` |
| `qdrant` | Vector search collections | `127.0.0.1:6333` |
| `ollama` | Local answer generation and embeddings | `127.0.0.1:11434` |
| `judge-ollama` | Dedicated Judge LLM runtime | `127.0.0.1:11435` |
| `worker` | Ingestion and extraction Celery worker | metrics on `127.0.0.1:9101` |
| `evaluation-worker` | Async judge evaluation worker | metrics on `127.0.0.1:9102` |
| `prometheus` | Metrics storage and queries | `http://localhost:9090` |
| `grafana` | Operations dashboard | `http://localhost:3001` |

The project name used for the main deployment is normally `rag-main`.

## Start, Stop, and Status

From the repository root:

```powershell
docker compose -p rag-main -f infrastructure/docker/docker-compose.yml up -d --build
```

Check service state:

```powershell
docker compose -p rag-main -f infrastructure/docker/docker-compose.yml ps
```

Follow logs:

```powershell
docker compose -p rag-main -f infrastructure/docker/docker-compose.yml logs -f api
docker compose -p rag-main -f infrastructure/docker/docker-compose.yml logs -f worker
docker compose -p rag-main -f infrastructure/docker/docker-compose.yml logs -f evaluation-worker
```

Stop without deleting volumes:

```powershell
docker compose -p rag-main -f infrastructure/docker/docker-compose.yml stop
```

Do not run `docker compose down -v` during normal operations. That deletes persisted data and model volumes.

## First Response Checklist

When an incident is reported:

1. Confirm the user-facing symptom, URL, time, role, domain, and action.
2. Check container health with `docker compose ... ps`.
3. Check API health at `http://localhost:8000/health`.
4. Check frontend at `http://localhost:3000`.
5. Check the newest logs for the failing service.
6. If the issue involves uploads or judge evaluation, check the matching Celery worker logs.
7. Preserve evidence before restarting if the issue may need investigation.

Useful health checks:

```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-WebRequest http://localhost:3000
Invoke-WebRequest http://localhost:9090/-/ready
Invoke-WebRequest http://localhost:3001
```

## Runbook: Frontend Shows 502

Likely cause: the frontend Nginx proxy cannot reach a healthy API container.

Checks:

```powershell
docker compose -p rag-main -f infrastructure/docker/docker-compose.yml ps
docker compose -p rag-main -f infrastructure/docker/docker-compose.yml logs --tail=120 api
Invoke-RestMethod http://localhost:8000/health
```

Response:

1. If `api` is exited or unhealthy, fix the API startup error first.
2. If `api` is healthy, check `frontend` logs and Nginx proxy config.
3. Recreate only the affected service after fixing the cause:

```powershell
docker compose -p rag-main -f infrastructure/docker/docker-compose.yml up -d --build api frontend
```

Expected recovery: `http://localhost:3000/api/v1/auth/token` should route to the backend, and the login page should no longer show a proxy error.

## Runbook: API Is Unhealthy or Crashes on Startup

Checks:

```powershell
docker compose -p rag-main -f infrastructure/docker/docker-compose.yml logs --tail=200 api
docker compose -p rag-main -f infrastructure/docker/docker-compose.yml ps postgres redis qdrant ollama
```

Common causes:

- missing Python dependency in the backend image
- invalid environment variable
- database schema or migration error
- Postgres not healthy
- Ollama or Qdrant unavailable during startup-dependent work

Response:

1. Read the first stack trace in the newest API logs.
2. Confirm dependency services are healthy.
3. If the error is a missing package, add it to the backend requirements used by Docker and rebuild the API image.
4. If the error is database-related, inspect the failing SQL and apply an idempotent migration.
5. Restart the API after the root cause is fixed.

## Runbook: Login Fails

Checks:

```powershell
docker compose -p rag-main -f infrastructure/docker/docker-compose.yml logs --tail=120 api
```

Local defaults:

- `DEV_MODE=true` in the Docker compose file.
- The seeded system admin is controlled by `ADMIN_EMAIL` and `ADMIN_PASSWORD`.
- Local default values are `admin@example.com` and `changeme123`.

Response:

1. Confirm the user is using the correct environment and URL.
2. Confirm the API is healthy.
3. Confirm the admin seed completed in API startup logs.
4. In production, do not use the local default password. Rotate it before launch.

## Runbook: Query Fails or Times Out

Symptoms:

- chat request returns `500`
- chat request returns `504`
- answer says there is not enough information
- citations are empty

Checks:

```powershell
docker compose -p rag-main -f infrastructure/docker/docker-compose.yml logs --tail=160 api
docker compose -p rag-main -f infrastructure/docker/docker-compose.yml logs --tail=120 ollama
docker compose -p rag-main -f infrastructure/docker/docker-compose.yml logs --tail=120 qdrant
```

Response:

1. Confirm the user has `reader` access to every selected domain.
2. Confirm the selected domain has completed documents and chunks.
3. Check whether Qdrant collections exist for the domain.
4. If the local model timed out, ask the user to narrow the question or select fewer documents, then inspect Ollama logs.
5. If retrieval finds no chunks, verify ingestion completed for the selected domain.
6. If SQL errors mention BM25 or full-text search, inspect the Postgres migration files under `infrastructure/docker/postgres/migrations`.

## Runbook: Upload Is Stuck

Symptoms:

- upload job stays `pending` or `processing`
- no chunks appear in the quality file view
- chat cannot retrieve from a recently uploaded file

Checks:

```powershell
docker compose -p rag-main -f infrastructure/docker/docker-compose.yml logs --tail=160 worker
docker compose -p rag-main -f infrastructure/docker/docker-compose.yml logs --tail=120 redis
```

Response:

1. Copy the job id from the Upload page.
2. Check `GET /api/v1/ingest/status/{job_id}`.
3. Confirm the worker is subscribed to `ingestion,extraction,celery`.
4. Check worker logs for extraction, OCR, embedding, or Qdrant errors.
5. Confirm file type is supported: PDF, DOCX, or CSV.
6. For large files, confirm Nginx allows the upload size. The frontend Nginx config should include a large enough `client_max_body_size`.

## Runbook: Duplicate or Changed File Upload

The ingestion API detects duplicate documents by content hash and detects changed files by filename.

Expected behavior:

- exact same file in the same domain returns a duplicate conflict
- same filename with different content returns a `file_changed` conflict
- replacement requires explicit confirmation through `POST /api/v1/ingest/replace`

Response:

1. Do not manually delete data unless the admin confirms replacement or deletion.
2. If replacement is intended, use the old document id from the conflict response.
3. After replacement, verify the new job completes.

## Runbook: Judge Evaluation or Moderation Is Not Updating

Symptoms:

- Chat shows `Judge pending` for a long time
- Quality dashboard has stale scores
- Moderation queue does not update

Checks:

```powershell
docker compose -p rag-main -f infrastructure/docker/docker-compose.yml ps evaluation-worker judge-ollama redis
docker compose -p rag-main -f infrastructure/docker/docker-compose.yml logs --tail=180 evaluation-worker
docker compose -p rag-main -f infrastructure/docker/docker-compose.yml logs --tail=120 judge-ollama
```

Response:

1. Confirm Redis is running.
2. Confirm `evaluation-worker` is subscribed to the `evaluation` queue.
3. Confirm `judge-ollama` has the configured `JUDGE_MODEL`.
4. Check for Judge timeout or model loading errors.
5. Restart `evaluation-worker` only after confirming Redis and judge runtime are available.

## Runbook: Grafana or Prometheus Is Blank

Checks:

```powershell
docker compose -p rag-main -f infrastructure/docker/docker-compose.yml ps prometheus grafana api worker evaluation-worker qdrant
Invoke-WebRequest http://localhost:9090/-/ready
Invoke-WebRequest http://localhost:3001
```

Response:

1. In Prometheus, check targets for `rag-api`, `rag-workers`, and `qdrant`.
2. If API metrics are missing, check `http://localhost:8000/metrics`.
3. If worker metrics are missing, check `worker:9090` and `evaluation-worker:9090` from inside the Docker network.
4. If Grafana is running but dashboards are missing, confirm provisioning files under `infrastructure/docker/grafana/provisioning`.

## Runbook: Disk or Volume Pressure

Persistent volumes:

- `postgres_data`
- `qdrant_data`
- `redis_data`
- `rag-main-ollama`
- `judge_ollama_data`
- `prometheus_data`
- `grafana_data`

Response:

1. Check disk usage before deleting anything.
2. Preserve `postgres_data`, `qdrant_data`, and `rag-main-ollama` unless a reset is explicitly approved.
3. Prometheus retention can be adjusted if metrics volume grows too large.
4. Export required data before destructive cleanup.

## On-Call Handoff

Each handoff should include:

- current branch and commit
- deployment command used
- current `docker compose ps` state
- known failing services
- recent incident timeline
- user impact
- unresolved risks
- any manual changes made outside Git

## Post-Incident Review

After a production-impacting incident:

1. Record what happened.
2. Record exact start and end times.
3. Identify the root cause.
4. Identify what detection failed or worked.
5. Add or update a runbook step.
6. Add a test, dashboard panel, alert, or validation check when practical.

## Acceptance Checklist

- Operators know how to start, stop, and inspect the stack.
- Common failures have concrete first checks.
- Runbooks avoid deleting volumes by default.
- On-call handoff data is defined.
- Incidents produce a follow-up improvement.
