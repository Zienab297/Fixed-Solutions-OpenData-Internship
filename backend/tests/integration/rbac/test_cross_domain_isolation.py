"""
Cross-domain isolation tests.

The core assertion everywhere here is ABSENCE: a user with no entitlement to
a domain must get zero hits referencing that domain's content, not just hits
ranked below some threshold. A document leaking in at rank 50 is just as much
a failure as one leaking in at rank 1 - RBAC isn't a relevance signal.
"""

import pytest
from . import config


def _assert_no_leak(response, forbidden_doc_ids, forbidden_probe_terms):
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}: {response.text}"
    )
    body = response.json()
    returned_doc_ids = {hit.get("doc_id") for hit in body.get("results", [])}
    leaked_ids = returned_doc_ids & set(forbidden_doc_ids)
    assert not leaked_ids, f"RBAC LEAK: forbidden doc_ids returned: {leaked_ids}"

    # Belt-and-suspenders: also check raw text/snippets for the probe term,
    # in case a doc_id field is renamed/omitted somewhere in the response.
    full_text = str(body).lower()
    for term in forbidden_probe_terms:
        assert term.lower() not in full_text, (
            f"RBAC LEAK: forbidden probe term '{term}' appeared in response"
        )


class TestCrossDomainLeakage:

    def test_legal_user_cannot_see_medical_only_doc(self, api_client_for):
        client = api_client_for("single_domain_legal")
        medical_doc = config.SEED_DOCS["medical_only_doc"]
        resp = client.query(medical_doc["unique_probe_term"])
        _assert_no_leak(
            resp,
            forbidden_doc_ids=[medical_doc["doc_id"]],
            forbidden_probe_terms=[medical_doc["unique_probe_term"]],
        )

    def test_medical_user_cannot_see_legal_only_doc(self, api_client_for):
        client = api_client_for("single_domain_medical")
        legal_doc = config.SEED_DOCS["legal_only_doc"]
        resp = client.query(legal_doc["unique_probe_term"])
        _assert_no_leak(
            resp,
            forbidden_doc_ids=[legal_doc["doc_id"]],
            forbidden_probe_terms=[legal_doc["unique_probe_term"]],
        )

    def test_legal_user_cannot_see_cs_only_doc(self, api_client_for):
        """cs is the one domain with a real seeded document, so this is the
        most meaningful "does isolation actually bite" check available until
        legal/medical get their own seeded docs."""
        client = api_client_for("single_domain_legal")
        cs_doc = config.SEED_DOCS["cs_only_doc"]
        resp = client.query(cs_doc["unique_probe_term"])
        _assert_no_leak(
            resp,
            forbidden_doc_ids=[cs_doc["doc_id"]],
            forbidden_probe_terms=[cs_doc["unique_probe_term"]],
        )

    def test_no_domain_user_sees_nothing_domain_scoped(self, api_client_for):
        """User with zero domain roles should get zero results from any
        domain-scoped corpus, even for very generic/common query terms that
        would normally surface lots of hits."""
        client = api_client_for("no_domains")
        for doc in config.SEED_DOCS.values():
            resp = client.query(doc["unique_probe_term"])
            _assert_no_leak(
                resp,
                forbidden_doc_ids=[doc["doc_id"]],
                forbidden_probe_terms=[doc["unique_probe_term"]],
            )

    @pytest.mark.parametrize("page_size", [5, 10, config.MAX_TOP_K])
    def test_no_leak_at_depth(self, api_client_for, page_size):
        """Re-run the leak check at increasing result depths (bounded by the
        API's own top_k ceiling - see config.MAX_TOP_K). A filter that's
        applied only as a post-hoc top-k truncation (rather than at the
        retrieval/query level) can pass shallow tests but leak once page size
        grows or a low-relevance forbidden doc still clears the cutoff."""
        client = api_client_for("single_domain_legal")
        cs_doc = config.SEED_DOCS["cs_only_doc"]
        resp = client.query(cs_doc["unique_probe_term"], top_k=page_size)
        _assert_no_leak(
            resp,
            forbidden_doc_ids=[cs_doc["doc_id"]],
            forbidden_probe_terms=[cs_doc["unique_probe_term"]],
        )

    def test_direct_document_fetch_blocked_by_id(self, api_client_for):
        """Even if search filtering is airtight, direct GET /documents/{id}
        must independently enforce domain entitlement. Don't rely on the
        retrieval layer's filter to be the only gate in the system."""
        client = api_client_for("single_domain_legal")
        cs_doc = config.SEED_DOCS["cs_only_doc"]
        resp = client.get_document(cs_doc["doc_id"])
        assert resp.status_code in (403, 404), (
            f"Expected 403/404 fetching out-of-domain doc directly by id, "
            f"got {resp.status_code}: {resp.text}"
        )
