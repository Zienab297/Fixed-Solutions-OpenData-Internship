# ADR 0001: Domain-Aware LLM Routing

## Status

Accepted for Sprint 1 walking skeleton.

## Context

The MVP supports multiple users and multiple knowledge domains. Some domains may contain internal, regulated, or sensitive content. Other domains may safely use an external model API for higher quality or lower local infrastructure cost.

The query service needs a clear generation routing rule before Sprint 1 implementation begins.

## Decision

Generation is routed by domain policy:

- `local`: use `Qwen/Qwen3-8B` loaded in 4-bit on Google Colab and exposed to the FastAPI backend through `LOCAL_LLM_BASE_URL`.
- `api`: use the Gemini API with `gemini-3.5-flash`.

When a user asks a question across multiple domains, the most restrictive route wins:

- If any selected domain is `local`, the whole request uses `local`.
- If every selected domain is `api`, the request may use `api`.
- If route metadata is missing, invalid, or unavailable, the request defaults to `local`.

The API response and audit record include the selected route.

For Sprint 1 development, Colab is the selected local-model host. The backend calls it through `LOCAL_LLM_BASE_URL`, so the route decision does not depend on Colab-specific code.

## Rationale

This keeps the first sprint safe and simple. A domain is already the main access-control boundary, so it is also the natural policy boundary for LLM routing. Defaulting to `local` prevents accidental leakage while configuration and admin UI features are still immature.

`Qwen/Qwen3-8B` in 4-bit is the chosen local development model because it is a safer fit for Colab GPU memory than a 12B Q6 model, has strong multilingual support, and is suitable for RAG answer generation. `gemini-3.5-flash` is the chosen API model for general-domain questions.

## Consequences

Positive outcomes:

- Sensitive content is protected by default.
- Multi-domain queries cannot leak local-only context to an external provider.
- The route decision is deterministic and easy to test.
- Future providers can be added behind the same router interface.

Tradeoffs:

- Mixed-domain requests use the local model even when some selected domains allow external routing.
- Admins need a later management UI/API for changing `llm_route`.
- Production external routing still needs stronger redaction, logging, and monitoring.

## Sprint 1 Implementation Notes

Sprint 1 provides:

- A small `LLMRouter` service.
- A local adapter for a Colab-hosted `Qwen/Qwen3-8B` 4-bit endpoint.
- A Gemini adapter for `gemini-3.5-flash`.
- Unit tests for route selection.
- Docker Compose wiring for the Sprint 1 API/frontend skeleton only.
- Mermaid diagrams for review and planning.

## Follow-Up Work

- Add domain admin endpoints for updating `llm_route`.
- Persist query audit records with selected route and provider latency.
- Decide production hosting for the local model endpoint outside Colab.
- Add per-document sensitivity labels.
- Add prompt/context redaction before external routing.
- Add provider health checks and fallback behavior.
