#!/usr/bin/env python3
"""
Manual smoke test script.
Run this from the backend/ folder after docker compose is up.

Usage:
    python tests/smoke_test.py
"""
import asyncio
import httpx

BASE = "http://localhost:8000/api/v1"

# ── Replace with a real token from Keycloak, or use an API key ──────
# For testing without Keycloak, temporarily comment out auth in get_current_user
HEADERS = {"Authorization": "Bearer <your-token-here>"}


async def test_health():
    async with httpx.AsyncClient() as client:
        r = await client.get("http://localhost:8000/health")
        assert r.status_code == 200
        print(f"✓ Health: {r.json()}")


async def test_create_domain():
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{BASE}/domains/",
            json={"name": "test-domain", "description": "Smoke test domain"},
            headers=HEADERS,
        )
        print(f"✓ Create domain: {r.status_code} — {r.json()}")
        return r.json().get("id")


async def test_ingest_document(domain_id: str):
    async with httpx.AsyncClient(timeout=30.0) as client:
        with open("tests/sample.pdf", "rb") as f:
            r = await client.post(
                f"{BASE}/ingest/document",
                data={"domain_id": domain_id},
                files={"file": ("sample.pdf", f, "application/pdf")},
                headers=HEADERS,
            )
        print(f"✓ Ingest: {r.status_code} — {r.json()}")
        return r.json().get("job_id"), r.json().get("document_id")


async def test_ingest_duplicate(domain_id: str):
    """Same file again — should return 409 exact duplicate."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        with open("tests/sample.pdf", "rb") as f:
            r = await client.post(
                f"{BASE}/ingest/document",
                data={"domain_id": domain_id},
                files={"file": ("sample.pdf", f, "application/pdf")},
                headers=HEADERS,
            )
        assert r.status_code == 409
        assert r.json()["detail"]["error"] == "duplicate_document"
        print(f"✓ Duplicate detection: correctly returned 409")


async def test_job_status(job_id: str):
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{BASE}/ingest/status/{job_id}", headers=HEADERS)
        print(f"✓ Job status: {r.json()}")


async def test_query(domain_id: str):
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(
            f"{BASE}/query",
            json={
                "query": "What is this document about?",
                "domain_ids": [domain_id],
                "domain_routes": {domain_id: "local"},
                "top_k": 3,
            },
            headers=HEADERS,
        )
        print(f"✓ Query: {r.status_code} — {r.json()}")


async def test_local_embed():
    """Direct local embedding test — bypasses the whole app."""
    from app.services.ingestion.embedder import EmbeddingService

    vec = await EmbeddingService().embed("hello world")
    print(f"✓ Local embed: dim={len(vec)}, first3={vec[:3]}")


async def main():
    print("\n=== Smoke Tests ===\n")
    await test_health()
    await test_local_embed()

    domain_id = await test_create_domain()
    if not domain_id:
        print("✗ Domain creation failed — stopping")
        return

    job_id, doc_id = await test_ingest_document(domain_id)
    if job_id:
        await asyncio.sleep(3)  # give Celery a moment
        await test_job_status(job_id)

    await test_ingest_duplicate(domain_id)

    # Wait for processing before querying
    print("\nWaiting 10s for document processing...")
    await asyncio.sleep(10)
    await test_query(domain_id)

    print("\n=== All smoke tests passed ===\n")


if __name__ == "__main__":
    asyncio.run(main())
