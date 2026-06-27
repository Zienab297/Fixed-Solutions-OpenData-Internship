"""
Shared document boundary tests.

A document tagged to multiple domains (e.g. legal + medical) is a classic
leak vector: a single-domain user should be able to retrieve it (since
they're entitled to one of its domains), but the response should not
expose the document's OTHER domain tags or any content gated specifically
to the domain they don't have. This is subtler than the binary
visible/not-visible check in the cross-domain tests.

NOTE: this whole file needs shared_legal_medical_doc to be a real, indexed
document tagged to both legal and medical. Until config.SEED_DOCS[
'shared_legal_medical_doc']['seeded'] is True with a real doc_id/probe term,
these tests are skipped - there's nothing real to retrieve.
"""

import pytest
from . import config

_shared_doc = config.SEED_DOCS["shared_legal_medical_doc"]
_SKIP_REASON = (
    "shared_legal_medical_doc is not seeded yet "
    "(config.SEED_DOCS['shared_legal_medical_doc']['seeded'] is False). "
    "Ingest a real document tagged to both legal and medical domains, "
    "fill in its doc_id/unique_probe_term, and flip 'seeded' to True."
)


@pytest.mark.skipif(not _shared_doc["seeded"], reason=_SKIP_REASON)
class TestSharedDocumentBoundary:

    def test_single_domain_user_can_retrieve_shared_doc(self, api_client_for):
        """Confirms the shared doc is reachable at all for an entitled user -
        a sanity check so a failure in the next test can't be confused with
        the doc simply being unreachable."""
        client = api_client_for("single_domain_legal")
        shared_doc = config.SEED_DOCS["shared_legal_medical_doc"]
        resp = client.query(shared_doc["unique_probe_term"])
        assert resp.status_code == 200
        ids = {hit.get("doc_id") for hit in resp.json().get("results", [])}
        assert shared_doc["doc_id"] in ids

    def test_shared_doc_response_does_not_expose_unentitled_domain_tags(self, api_client_for):
        """The legal user retrieving the shared doc should not see 'medical'
        in any domain-tag metadata field on the hit. If your API surfaces a
        `domains` or `tags` field per result, it must be filtered to the
        intersection of (doc's domains) and (user's domains), not the doc's
        full domain list."""
        client = api_client_for("single_domain_legal")
        shared_doc = config.SEED_DOCS["shared_legal_medical_doc"]
        resp = client.query(shared_doc["unique_probe_term"])
        assert resp.status_code == 200
        hits = resp.json().get("results", [])
        matching = [h for h in hits if h.get("doc_id") == shared_doc["doc_id"]]
        assert matching, "Shared doc not found in results"

        for hit in matching:
            exposed_domains = set(hit.get("domains", []) or hit.get("tags", []))
            assert "medical" not in exposed_domains, (
                f"Shared doc response exposed 'medical' domain tag to a "
                f"user who only has 'legal' entitlement: {hit}"
            )

    def test_graph_neighbors_of_shared_doc_respect_requester_domain(self, api_client_for):
        """If the knowledge graph links the shared doc to medical-only
        entities (e.g. a medical-specific skill/relationship node), a legal
        user querying through/around that doc must not have those
        medical-only graph neighbors surfaced via graph expansion."""
        client = api_client_for("single_domain_legal")
        shared_doc = config.SEED_DOCS["shared_legal_medical_doc"]
        medical_doc = config.SEED_DOCS["medical_only_doc"]
        resp = client.query(shared_doc["unique_probe_term"], expand_graph=True)
        assert resp.status_code == 200
        full_text = str(resp.json()).lower()
        assert medical_doc["unique_probe_term"].lower() not in full_text, (
            "Graph expansion from a shared doc leaked a medical-only "
            "neighbor node into a legal-only user's response"
        )
