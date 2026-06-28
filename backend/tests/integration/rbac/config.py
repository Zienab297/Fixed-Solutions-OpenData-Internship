"""
Central config for RBAC isolation test suite.
"""

import os

# ---------------------------------------------------------------------------
# Keycloak
# ---------------------------------------------------------------------------
KEYCLOAK_BASE_URL = os.getenv("KEYCLOAK_BASE_URL", "http://localhost:8080")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "rag")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "rag-api")
KEYCLOAK_CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET", "secret")

KEYCLOAK_TOKEN_URL = (
    f"{KEYCLOAK_BASE_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"
)

KEYCLOAK_ADMIN_BASE_URL = os.getenv("KEYCLOAK_ADMIN_BASE_URL", KEYCLOAK_BASE_URL)
KEYCLOAK_ADMIN_REALM = os.getenv("KEYCLOAK_ADMIN_REALM", "master")
KEYCLOAK_ADMIN_CLIENT_ID = os.getenv("KEYCLOAK_ADMIN_CLIENT_ID", "admin-cli")
KEYCLOAK_ADMIN_USER = os.getenv("KEYCLOAK_ADMIN_USER", "admin@example.com")
KEYCLOAK_ADMIN_PASSWORD = os.getenv("KEYCLOAK_ADMIN_PASSWORD", "changeme123")
TARGET_REALM = KEYCLOAK_REALM

# ---------------------------------------------------------------------------
# RAG API
# ---------------------------------------------------------------------------
API_BASE_URL = os.getenv("RAG_API_BASE_URL", "http://localhost:8000/api/v1")

ENDPOINTS = {
    "query": "/query",
    "query_bm25_only": "/query/bm25",
    "query_vector_only": "/query/vector",
    "query_graph_only": "/query/graph",
    "documents": "/documents",
    "health": "/health",
}

# Hard ceiling enforced by the API's request schema (top_k: le=20).
# Tests that probe "leak at depth" must stay within this bound.
MAX_TOP_K = 20

# ---------------------------------------------------------------------------
# Domains
# ---------------------------------------------------------------------------
DOMAINS = {
    "legal": "domain:legal",
    "medical": "domain:medical",
    "cs": "domain:computer science",  # actual domain name in DB is "computer science"
}

# ---------------------------------------------------------------------------
# Test users
# ---------------------------------------------------------------------------
TEST_USERS = {
    "single_domain_legal": {
        "username": "test_legal_user@example.com",
        "password": "ChangeMe123!",
        "roles": ["domain:legal"],
    },
    "single_domain_medical": {
        "username": "test_medical_user@example.com",
        "password": "ChangeMe123!",
        "roles": ["domain:medical"],
    },
    "single_domain_cs": {
        "username": "test_cs_user@example.com",
        "password": "ChangeMe123!",
        "roles": ["domain:cs"],
    },
    "multi_domain_legal_medical": {
        "username": "test_legal_medical_user@example.com",
        "password": "ChangeMe123!",
        "roles": ["domain:legal", "domain:medical"],
    },
    "no_domains": {
        "username": "test_no_access_user@example.com",
        "password": "ChangeMe123!",
        "roles": [],
    },
    "revocable_user": {
        "username": "test_revocable_user@example.com",
        "password": "ChangeMe123!",
        "roles": ["domain:legal"],
    },
}

# ---------------------------------------------------------------------------
# Known seed documents
# ---------------------------------------------------------------------------
# IMPORTANT: only `cs` currently has real seeded documents in the corpus.
# `legal` and `medical` have NO documents yet, which means any test that
# asserts a *positive* hit (e.g. "multi-domain user CAN see this doc",
# "shared doc IS retrievable") for legal/medical will fail not because of
# an RBAC bug, but because there is nothing there to find.
#
# Tests that assert ABSENCE (cross-domain isolation, no-leak-at-depth) still
# work fine against empty domains - querying a probe term that doesn't exist
# anywhere correctly returns zero hits regardless of RBAC behavior, so those
# don't actually exercise the isolation logic in a meaningful way either.
#
# To properly test union/shared-document logic you need real, indexed
# documents in at least two domains. Until legal/medical are seeded:
#   - legal_only_doc / medical_only_doc / shared_legal_medical_doc are
#     placeholders and tests depending on them are expected to fail/skip.
#   - cs_only_doc is real and safe to use as the "has documents" side of
#     any single-domain positive-hit test.
SEED_DOCS = {
    "legal_only_doc": {
        "doc_id": "ebcf4b35-aff2-4a65-baea-7fe12b21320e",
        "domains": ["legal"],
        "unique_probe_term": "ZZPROBE-LEGAL-7f3a91",
        "seeded": True,
    },
    "medical_only_doc": {
        "doc_id": "9704a75f-7004-4cc5-8dbb-0c520192056d",
        "domains": ["medical"],
        "unique_probe_term": "ZZPROBE-MEDICAL-c4e02d",
        "seeded": True,
    },
    "shared_legal_medical_doc": {
        "doc_id": "7a2853b9-9d55-4493-9199-08b3a90cbd76",
        "domains": ["legal", "medical"],
        "unique_probe_term": "ZZPROBE-SHARED-91bd6a",
        "seeded": True,
    },
    "cs_only_doc": {
        "doc_id": "TODO-doc-id-cs-only",  # still need this from seed script
        "domains": ["computer science"],
        "unique_probe_term": "ZZPROBE-CS-b8f14e",
        "seeded": True,
    },
}

REQUEST_TIMEOUT_SECONDS = 15