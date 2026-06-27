"""
Multi-role union tests.

A user with roles spanning multiple domains should see the UNION of all
entitled domains' content. The common bug here is a filter implementation
that only applies the first matched role/domain (e.g. iterates roles and
`break`s after building one filter clause) instead of OR-ing all of them.

NOTE: legal and medical currently have no seeded documents (only cs does).
These tests are skipped until legal_only_doc / medical_only_doc in
config.SEED_DOCS are marked seeded=True with real doc_id/probe values -
otherwise a "positive hit" assertion here can never pass regardless of
whether the union logic is correct, which would just be noise.
"""

import pytest
from . import config

_legal_doc = config.SEED_DOCS["legal_only_doc"]
_medical_doc = config.SEED_DOCS["medical_only_doc"]
_NEEDS_SEEDED_DOCS = not (_legal_doc["seeded"] and _medical_doc["seeded"])
_SKIP_REASON = (
    "legal_only_doc and/or medical_only_doc are not seeded yet "
    "(config.SEED_DOCS[...]['seeded'] is False) - only cs has real "
    "documents right now, so union-of-domains tests have nothing to "
    "positively assert against. Seed one real doc into each of legal "
    "and medical, fill in their doc_id/unique_probe_term, and flip "
    "'seeded' to True to enable these tests."
)


class TestMultiRoleUnionAbsenceOnly:
    """Absence-only check that doesn't depend on legal/medical being seeded -
    it only needs the real cs_only_doc to confirm union access didn't
    accidentally widen to domains the user has no role for."""

    def test_multi_domain_user_still_excluded_from_unassigned_domain(self, api_client_for):
        """Union isn't the same as 'all domains'. A user with legal+medical
        should still be blocked from e.g. cs-only content."""
        client = api_client_for("multi_domain_legal_medical")
        cs_doc = config.SEED_DOCS["cs_only_doc"]
        resp = client.query(cs_doc["unique_probe_term"])
        assert resp.status_code == 200
        full_text = str(resp.json()).lower()
        assert cs_doc["unique_probe_term"].lower() not in full_text


@pytest.mark.skipif(_NEEDS_SEEDED_DOCS, reason=_SKIP_REASON)
class TestMultiRoleUnion:

    def test_multi_domain_user_sees_both_domains(self, api_client_for):
        client = api_client_for("multi_domain_legal_medical")
        legal_doc = config.SEED_DOCS["legal_only_doc"]
        medical_doc = config.SEED_DOCS["medical_only_doc"]

        legal_resp = client.query(legal_doc["unique_probe_term"])
        assert legal_resp.status_code == 200
        legal_ids = {hit.get("doc_id") for hit in legal_resp.json().get("results", [])}
        assert legal_doc["doc_id"] in legal_ids, (
            "Multi-domain user failed to retrieve legal doc - union filter may "
            "only be applying one of the user's roles"
        )

        medical_resp = client.query(medical_doc["unique_probe_term"])
        assert medical_resp.status_code == 200
        medical_ids = {hit.get("doc_id") for hit in medical_resp.json().get("results", [])}
        assert medical_doc["doc_id"] in medical_ids, (
            "Multi-domain user failed to retrieve medical doc - union filter "
            "may be dropping later roles in the list"
        )

    def test_role_order_does_not_affect_union_result(self, api_client_for, keycloak_admin, token_for, bust_token_cache, wait_for_propagation):
        """Regression guard for the 'first matched role wins' bug class:
        strip the user down to a single role, confirm scoped access, then
        add the second role back and confirm the union grows rather than
        staying pinned to whichever role happened to be evaluated first.

        Mutates the dedicated 'revocable_user' fixture user so it doesn't
        interfere with other parametrized tests running concurrently.
        """
        user = config.TEST_USERS["revocable_user"]
        user_id = keycloak_admin.get_user_id(user["username"])

        # Ensure starting state: only domain:legal
        keycloak_admin.add_realm_role_to_user(user_id, "domain:legal")
        keycloak_admin.logout_user_sessions(user_id)
        bust_token_cache("revocable_user")
        wait_for_propagation()

        client = api_client_for("revocable_user")
        legal_doc = config.SEED_DOCS["legal_only_doc"]
        resp = client.query(legal_doc["unique_probe_term"])
        ids = {hit.get("doc_id") for hit in resp.json().get("results", [])}
        assert legal_doc["doc_id"] in ids

        # Now add domain:medical on top and confirm union grows
        keycloak_admin.add_realm_role_to_user(user_id, "domain:medical")
        keycloak_admin.logout_user_sessions(user_id)
        bust_token_cache("revocable_user")
        wait_for_propagation()

        client = api_client_for("revocable_user")
        medical_doc = config.SEED_DOCS["medical_only_doc"]
        resp = client.query(medical_doc["unique_probe_term"])
        ids = {hit.get("doc_id") for hit in resp.json().get("results", [])}
        assert medical_doc["doc_id"] in ids, (
            "Adding a second role did not expand access - union logic may "
            "be pinned to whichever role was evaluated/cached first"
        )

        # Cleanup: restore to single-role baseline for other tests
        keycloak_admin.remove_realm_role_from_user(user_id, "domain:medical")
        keycloak_admin.logout_user_sessions(user_id)
        bust_token_cache("revocable_user")
