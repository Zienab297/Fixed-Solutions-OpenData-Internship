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
