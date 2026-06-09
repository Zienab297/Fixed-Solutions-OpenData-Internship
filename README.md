# Sprint 1: Infrastructure, LLM Routing, and Architecture Diagrams

This folder is a standalone Sprint 1 work package. It is intentionally created from zero and does not depend on the existing project files.

## Scope

This package covers the assigned Sprint 1 tasks:

- ADR: LLM Routing
- Monorepo skeleton
- CI/CD skeleton
- Docker Compose local stack
- Architecture diagrams
- React web UI for login, chat, and PDF upload
- PDF ingestion API skeleton with Celery, Redis, pdfplumber, sentence-transformers, and Qdrant

## Folder Layout

```text
sprint1-infra-llm-routing-diagrams/
  .github/workflows/ci.yml
  backend/
    app/
      ingestion/
  docs/
    adr/
    architecture/
  frontend/
    src/
  infrastructure/
    docker/
  shared/
```

## Local Run

From this folder:

```powershell
docker compose -f infrastructure/docker/docker-compose.yml up --build
```

Useful URLs:

- API health: http://localhost:8000/health
- API docs: http://localhost:8000/docs
- Frontend app: http://localhost:3000

The Compose stack runs the API, React frontend, Redis broker, Celery worker, and Qdrant vector database. Graph DB and observability remain documented integration points for later sprint work.

## Frontend Dev Run

```powershell
cd frontend
npm install
npm run dev
```

The Vite dev server proxies `/api` calls to `http://localhost:8000`.

## Backend Test Run

```powershell
python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
python -m pytest
```

## Ingestion Flow

The upload page calls `POST /api/v1/ingest` with a PDF file and `domain_id`. The API saves the file, creates an `ingestion_jobs` record with `pending` status, enqueues a Celery task, and returns the job immediately. The frontend polls `GET /api/v1/ingest/{job_id}` every 2 seconds.

The worker extracts text with `pdfplumber`, skips OCR for scanned PDFs in Sprint 1, chunks text with a simple overlapping character splitter, embeds chunks with `sentence-transformers` using `EMBEDDING_MODEL`, and upserts chunk vectors and payload metadata into Qdrant.

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
