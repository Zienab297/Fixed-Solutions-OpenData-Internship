"""
Per-retrieval-path parity tests.

The hybrid pipeline fuses three signals (BM25/RRF text search, Qdrant vector
search, Apache AGE graph search) before producing final results. RBAC
filtering needs to be enforced on EACH path independently, before fusion -
not just on the final merged/fused list. If one path's filter clause is out
of sync (e.g. someone forgot to add the domain predicate to the Cypher/AGE
query when refactoring), that path can leak candidates into RRF that then
surface in the final ranking even though the other two paths correctly
excluded them.

These tests assume debug/internal endpoints exist that expose each path in
isolation (see config.ENDPOINTS). If those don't exist yet, this is the
strongest argument for adding them - even if gated behind an admin-only
debug flag - because without them you can only ever test the fused output,
which is exactly the layer that can mask a single-path leak.

NOTE: uses the legal user as the requester and cs_only_doc as the forbidden
target, since cs is currently the only domain with real, indexed documents.
legal has no documents of its own yet, which is fine here - the test only
needs the requester to lack cs entitlement, not to have content of its own.
"""

import pytest
from . import config


PATH_ENDPOINTS = [
    "query_bm25_only",
    "query_vector_only",
    "query_graph_only",
]


class TestRetrievalPathParity:

    @pytest.mark.parametrize("endpoint_key", PATH_ENDPOINTS)
    def test_path_excludes_out_of_domain_doc(self, api_client_for, endpoint_key):
        client = api_client_for("single_domain_legal")
        cs_doc = config.SEED_DOCS["cs_only_doc"]
        resp = client.query(cs_doc["unique_probe_term"], endpoint_key=endpoint_key)

        if resp.status_code == 404:
            pytest.skip(
                f"Debug endpoint for {endpoint_key} not implemented yet - "
                f"add config.ENDPOINTS['{endpoint_key}'] to exercise this path "
                f"in isolation. Until it exists, this path's filter can only "
                f"be verified indirectly through the fused /query endpoint."
            )

        assert resp.status_code == 200, f"{endpoint_key}: {resp.status_code} {resp.text}"
        body = resp.json()
        ids = {hit.get("doc_id") for hit in body.get("results", [])}
        assert cs_doc["doc_id"] not in ids, (
            f"RBAC LEAK isolated to {endpoint_key}: this retrieval path "
            f"returned an out-of-domain doc that the fused pipeline might "
            f"otherwise mask if another path's score dominates RRF"
        )

    def test_fused_result_never_exceeds_union_of_path_results(self, api_client_for):
        """Sanity invariant: nothing should appear in the fused /query
        response that doesn't appear in at least one of the three
        individual-path responses for the same query. A doc appearing only
        in the fused output (and in none of the three raw paths) would
        indicate a bug in the fusion/RRF step itself, e.g. merging an
        unfiltered candidate pool before filters are applied per-path.

        Uses the cs user querying for the real cs_only_doc, since cs is the
        only domain currently populated with indexed content - this is the
        one case where we can expect actual positive hits to compare across
        paths rather than three empty result sets agreeing trivially."""
        client = api_client_for("single_domain_cs")
        cs_doc = config.SEED_DOCS["cs_only_doc"]
        term = cs_doc["unique_probe_term"]

        fused = client.query(term, endpoint_key="query")
        assert fused.status_code == 200
        fused_ids = {hit.get("doc_id") for hit in fused.json().get("results", [])}

        union_ids = set()
        any_path_available = False
        for endpoint_key in PATH_ENDPOINTS:
            resp = client.query(term, endpoint_key=endpoint_key)
            if resp.status_code == 404:
                continue
            any_path_available = True
            union_ids |= {hit.get("doc_id") for hit in resp.json().get("results", [])}

        if not any_path_available:
            pytest.skip("No per-path debug endpoints available to compute union")

        extra = fused_ids - union_ids
        assert not extra, (
            f"Fused results contained doc_ids absent from all individual "
            f"retrieval paths: {extra}. Check whether RRF fusion is "
            f"merging from an unfiltered/pre-RBAC candidate pool."
        )
