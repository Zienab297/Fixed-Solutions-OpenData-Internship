"""
Shared fixtures for RBAC isolation tests.
Tokens are fetched from the app's /auth/token endpoint (not Keycloak directly).
"""

import time
import requests
import pytest

from . import config


# ---------------------------------------------------------------------------
# Token helpers — hit the app, not Keycloak
# ---------------------------------------------------------------------------

def _fetch_user_token(username: str, password: str) -> dict:
    resp = requests.post(
        f"{config.API_BASE_URL}/auth/token",
        data={"username": username, "password": password},
        timeout=config.REQUEST_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    return resp.json()


def _fetch_admin_token() -> dict:
    resp = requests.post(
        f"{config.API_BASE_URL}/auth/token",
        data={"username": config.KEYCLOAK_ADMIN_USER, "password": config.KEYCLOAK_ADMIN_PASSWORD},
        timeout=config.REQUEST_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    return resp.json()


@pytest.fixture(scope="session")
def admin_token():
    return _fetch_admin_token()["access_token"]


# ---------------------------------------------------------------------------
# Keycloak admin — role mutation for staleness/union tests.
# In DEV_MODE Keycloak isn't used, so these ops hit the app's domain
# membership endpoint instead.
# ---------------------------------------------------------------------------

class KeycloakAdmin:
    """
    Thin wrapper for role mutation.
    In DEV_MODE: uses GET /domains/ + POST /auth/users to grant/revoke roles.
    """

    def __init__(self, admin_token: str):
        self.token = admin_token
        self.headers = {
            "Authorization": f"Bearer {admin_token}",
            "Content-Type": "application/json",
        }
        self._domain_cache: dict = {}

    def _domains(self) -> dict:
        if not self._domain_cache:
            resp = requests.get(
                f"{config.API_BASE_URL}/domains/",
                headers=self.headers,
                timeout=config.REQUEST_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            self._domain_cache = {d["name"].lower(): d["id"] for d in resp.json()}
        return self._domain_cache

    def _domain_id(self, role_name: str) -> str:
        """Convert 'domain:legal' → domain id for 'legal'."""
        domain_name = role_name.split(":")[-1].lower()
        domains = self._domains()
        if domain_name not in domains:
            raise ValueError(f"Domain '{domain_name}' not found. Available: {list(domains.keys())}")
        return domains[domain_name]

    def get_user_id(self, username: str) -> str:
        # In our app, username = email. We return it as-is since our
        # add/remove calls use email directly.
        return username

    def get_realm_role(self, role_name: str) -> dict:
        # Compatibility shim — not used in DEV_MODE path.
        return {"name": role_name}

    def add_realm_role_to_user(self, user_id: str, role_name: str):
        domain_id = self._domain_id(role_name)
        user = _find_user_by_email(user_id)
        resp = requests.post(
            f"{config.API_BASE_URL}/auth/users",
            headers=self.headers,
            json={
                "email": user["username"],   # <-- was user["email"]
                "password": user["password"],
                "domain_id": domain_id,
                "role": "reader",
            },
            timeout=config.REQUEST_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()

    def remove_realm_role_from_user(self, user_id: str, role_name: str):
        """
        Revoke a domain role. The app doesn't have a DELETE membership endpoint
        exposed yet, so we mark the role as None by re-assigning with the lowest
        possible role, or you can add a DELETE /domains/{id}/members/{user_id}
        endpoint. For now this is a no-op stub that logs the intent.

        TODO: implement DELETE /domains/{domain_id}/members/{user_id} and wire it here.
        """
        domain_id = self._domain_id(role_name)
        print(f"[rbac-test] STUB: remove role {role_name} (domain {domain_id}) from {user_id}")
        print("[rbac-test] Add DELETE /domains/{id}/members/{user_id} to fully support revocation tests.")

    def logout_user_sessions(self, user_id: str):
        # DEV_MODE uses short-lived JWTs; no session store to clear.
        pass


def _find_user_by_email(email: str) -> dict:
    """Look up a test user entry by email across TEST_USERS."""
    for user in config.TEST_USERS.values():
        if user["username"] == email:
            return user
    raise KeyError(f"No TEST_USERS entry with username/email '{email}'")


@pytest.fixture(scope="session")
def keycloak_admin(admin_token):
    return KeycloakAdmin(admin_token)


# ---------------------------------------------------------------------------
# Per-test-user tokens
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def _token_cache():
    return {}


def _get_token_for(user_key: str, cache: dict) -> str:
    if user_key in cache:
        return cache[user_key]
    user = config.TEST_USERS[user_key]
    token_data = _fetch_user_token(user["username"], user["password"])
    cache[user_key] = token_data["access_token"]
    return cache[user_key]


@pytest.fixture
def token_for(_token_cache):
    def _inner(user_key: str) -> str:
        return _get_token_for(user_key, _token_cache)
    return _inner


@pytest.fixture
def bust_token_cache(_token_cache):
    def _inner(user_key: str):
        _token_cache.pop(user_key, None)
    return _inner


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------

class ApiClient:
    def __init__(self, token: str):
        self.headers = {"Authorization": f"Bearer {token}"}

    def query(self, text: str, endpoint_key: str = "query", **kwargs):
        url = config.API_BASE_URL + config.ENDPOINTS[endpoint_key]
        resp = requests.post(
            url,
            json={"query": text, **kwargs},
            headers=self.headers,
            timeout=config.REQUEST_TIMEOUT_SECONDS,
        )
        return resp

    def get_document(self, doc_id: str):
        url = f"{config.API_BASE_URL}{config.ENDPOINTS['documents']}/{doc_id}"
        return requests.get(url, headers=self.headers, timeout=config.REQUEST_TIMEOUT_SECONDS)


@pytest.fixture
def api_client_for(token_for):
    def _inner(user_key: str) -> ApiClient:
        return ApiClient(token_for(user_key))
    return _inner


@pytest.fixture
def wait_for_propagation():
    def _inner(seconds: float = 1.0):
        time.sleep(seconds)
    return _inner