# TLS and Secrets Management

## Purpose

This document explains how the RAG platform should protect traffic and secrets for Sprint 4 production readiness.

TLS means users connect through HTTPS so browser traffic is encrypted. Secrets management means passwords, API keys, JWT signing keys, and admin credentials are provided at deployment time instead of being hard-coded in the repository.

## Current Local Setup

Local development can still use:

```powershell
docker compose -p rag-main -f infrastructure/docker/docker-compose.yml up -d
```

The local compose file keeps developer-friendly defaults, but exposed service ports are bound to `127.0.0.1` so Postgres, Redis, Qdrant, Ollama, the API, Grafana, and Prometheus are not exposed to the network by default.

Local defaults are not production secrets.

## Production HTTPS Approach

Production HTTPS should use a reverse proxy in front of the app:

```text
Browser HTTPS
  -> Caddy edge proxy on ports 80 and 443
  -> frontend container
  -> API container through /api/*
```

The app containers continue talking to each other on the private Docker network. Only the edge proxy should be public.

This repository includes:

- `infrastructure/docker/docker-compose.tls.yml`
- `infrastructure/docker/caddy/Caddyfile`
- `.env.production.example`

When a real domain exists, copy `.env.production.example` to `.env`, set `APP_HOSTNAME`, replace all `CHANGE_ME` values, and run:

```powershell
docker compose -p rag-main `
  -f infrastructure/docker/docker-compose.yml `
  -f infrastructure/docker/docker-compose.tls.yml `
  up -d --build
```

Caddy will request and renew a public certificate automatically for the configured domain. DNS must point the domain to the deployment server before certificate issuance can work.

## No Domain Yet

Without a real domain, trusted public HTTPS cannot be completed. The project can still be prepared now:

- keep the Caddy reverse-proxy config in source control
- keep production secrets out of Git
- test local routing with `APP_HOSTNAME=localhost`
- replace `APP_HOSTNAME` when a domain is assigned

Local `localhost` HTTPS may show browser trust warnings because the certificate is not from a public certificate authority.

## Secret Inventory

These values must be treated as secrets in production:

| Secret | Used by | Production rule |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | Postgres, API, workers | Long random value, rotate if exposed |
| `REDIS_PASSWORD` | Redis, Celery workers | Long random value, rotate if exposed |
| `SECRET_KEY` | FastAPI JWT signing | 64+ random characters, rotate carefully |
| `ADMIN_PASSWORD` | initial admin seed | Change before launch |
| `GRAFANA_ADMIN_PASSWORD` | Grafana login | Change before launch |
| `KEYCLOAK_CLIENT_SECRET` | Keycloak integration if enabled | Store only in deployment secret store |
| external LLM API keys | optional external model route | Never commit, restrict by provider policy |

Non-secret configuration, such as model names and internal service URLs, may stay in examples.

## Required Practices

- Never commit real `.env` files.
- Keep `.env.example` local-only and `.env.production.example` placeholder-only.
- Use long, unique values for every production secret.
- Do not reuse the local admin password in production.
- Keep Postgres, Redis, Qdrant, Ollama, Prometheus, and Grafana behind private networking unless there is a documented reason to expose them.
- Rotate secrets after a suspected leak, staff handoff, or production migration.
- Store production secrets in the deployment platform, such as Docker secrets, Kubernetes Secrets, GitHub Actions secrets, or a cloud secret manager.

## Rotation Guide

1. Generate a replacement secret.
2. Put it into the production secret store or `.env` on the server.
3. Restart only the services that need the value.
4. Verify login, query, upload, worker, and dashboard flows.
5. Revoke or delete the old secret.

`SECRET_KEY` rotation invalidates existing JWT sessions, so users should be warned or logged out intentionally.

## Sprint 4 Acceptance Checklist

- HTTPS edge config exists.
- Production env template contains placeholders only.
- Local examples clearly warn against production use.
- Internal service ports are not exposed publicly by default.
- Documentation explains certificate requirements, secret inventory, and rotation.
