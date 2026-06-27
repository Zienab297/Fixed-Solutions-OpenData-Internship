"""
Token / role staleness tests.

When a role is revoked in Keycloak, the next request from that user must
respect the new (reduced) role set. Common leak vectors:
- A long-lived JWT whose claims are trusted at face value without checking
  revocation/session state (mitigated by short token TTL + introspection,
  or by forcing session logout as part of revocation).
- An app-side cache (Redis?) keyed by user_id that caches "allowed domains"
  and isn't invalidated when Keycloak role mappings change.
- A FastAPI dependency that decodes the JWT once per request but pulls
  cached role->domain mappings from a TTL cache that hasn't expired yet.

These tests use the dedicated `revocable_user` fixture so they don't
interfere with other tests that depend on stable role assignments.
"""

import time
import pytest
from . import config

_legal_doc = config.SEED_DOCS["legal_only_doc"]
_SKIP_REASON = (
    "legal_only_doc is not seeded yet "
    "(config.SEED_DOCS['legal_only_doc']['seeded'] is False) - this test "
    "needs a real, retrievable doc in 'legal' to confirm the baseline "
    "grant took effect before testing revocation."
)


@pytest.mark.skipif(not _legal_doc["seeded"], reason=_SKIP_REASON)
class TestTokenStaleness:

    def test_revoked_role_blocks_immediately_after_session_logout(
        self, api_client_for, keycloak_admin, token_for, bust_token_cache, wait_for_propagation
    ):
        user = config.TEST_USERS["revocable_user"]
        user_id = keycloak_admin.get_user_id(user["username"])

        # Baseline: grant domain:legal, confirm access
        keycloak_admin.add_realm_role_to_user(user_id, "domain:legal")
        keycloak_admin.logout_user_sessions(user_id)
        bust_token_cache("revocable_user")
        wait_for_propagation()

        client = api_client_for("revocable_user")
        legal_doc = config.SEED_DOCS["legal_only_doc"]
        resp = client.query(legal_doc["unique_probe_term"])
        ids = {hit.get("doc_id") for hit in resp.json().get("results", [])}
        assert legal_doc["doc_id"] in ids, "Baseline grant did not take effect - check role setup"

        # Revoke and force session logout (this is the "correct" revocation path -
        # token TTL alone is not a substitute for this if your access tokens
        # are long-lived)
        keycloak_admin.remove_realm_role_from_user(user_id, "domain:legal")
        keycloak_admin.logout_user_sessions(user_id)
        bust_token_cache("revocable_user")
        wait_for_propagation()

        client = api_client_for("revocable_user")
        resp = client.query(legal_doc["unique_probe_term"])
        assert resp.status_code == 200
        ids = {hit.get("doc_id") for hit in resp.json().get("results", [])}
        assert legal_doc["doc_id"] not in ids, (
            "RBAC LEAK: revoked role still grants access after session "
            "logout - check whether app-side caching (Redis, in-memory "
            "TTL cache) of role->domain mappings is being invalidated on "
            "Keycloak role changes, independent of token expiry"
        )

        # Restore baseline for any other test relying on this fixture user
        keycloak_admin.add_realm_role_to_user(user_id, "domain:legal")
        keycloak_admin.logout_user_sessions(user_id)
        bust_token_cache("revocable_user")

    @pytest.mark.skip(
        reason="Only meaningful if access tokens are long-lived (>60s). "
        "If your Keycloak client uses short-lived access tokens (e.g. 60-300s) "
        "with refresh-token rotation, this scenario is already mitigated by "
        "TTL and this test mainly documents that assumption. Un-skip and set "
        "SLEEP_SECONDS to (access_token_ttl + buffer) to verify it explicitly."
    )
    def test_old_access_token_rejected_or_filtered_after_revocation_without_logout(
        self, api_client_for, keycloak_admin, token_for, wait_for_propagation
    ):
        """Worst-case scenario: role is revoked but the user's existing
        access token is NOT explicitly invalidated (no logout_user_sessions
        call) and the client just keeps using the old token until it expires
        naturally. Confirms the token's claims-at-issue-time don't grant
        a grace period of stale access beyond what your TTL policy intends.
        """
        SLEEP_SECONDS = 90  # TODO: set to access_token_lifespan + buffer

        user = config.TEST_USERS["revocable_user"]
        user_id = keycloak_admin.get_user_id(user["username"])
        keycloak_admin.add_realm_role_to_user(user_id, "domain:legal")
        wait_for_propagation()

        client = api_client_for("revocable_user")  # token minted while role is active
        keycloak_admin.remove_realm_role_from_user(user_id, "domain:legal")
        # deliberately NOT calling logout_user_sessions here

        time.sleep(SLEEP_SECONDS)

        legal_doc = config.SEED_DOCS["legal_only_doc"]
        resp = client.query(legal_doc["unique_probe_term"])
        ids = {hit.get("doc_id") for hit in resp.json().get("results", [])}
        assert legal_doc["doc_id"] not in ids, (
            "Old access token retained domain access well past its "
            "expected lifespan - confirm access_token_lifespan in Keycloak "
            "client settings matches what you assume elsewhere in the system"
        )

        keycloak_admin.add_realm_role_to_user(user_id, "domain:legal")