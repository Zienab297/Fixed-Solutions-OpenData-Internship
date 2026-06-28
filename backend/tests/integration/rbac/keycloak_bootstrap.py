"""
RBAC test user bootstrap.

Goes through your actual API (not Keycloak admin directly).
Requires the FastAPI server to be running on API_BASE_URL.

Usage:
    python keycloak_bootstrap.py
"""

import sys
import requests

API_BASE_URL = "http://localhost:8000/api/v1"
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "changeme123"

# Each entry = one domain role assignment.
# Same email appearing twice = user gets two domain roles.
TEST_USERS = [
    {"email": "test_legal_user@example.com",         "password": "ChangeMe123!", "domain": "legal",   "role": "reader"},
    {"email": "test_medical_user@example.com",        "password": "ChangeMe123!", "domain": "medical", "role": "reader"},
    {"email": "test_cs_user@example.com",             "password": "ChangeMe123!", "domain": "computer science", "role": "reader"},
    {"email": "test_legal_medical_user@example.com",  "password": "ChangeMe123!", "domain": "legal",   "role": "reader"},
    {"email": "test_legal_medical_user@example.com",  "password": "ChangeMe123!", "domain": "medical", "role": "reader"},
    {"email": "test_no_access_user@example.com",      "password": "ChangeMe123!", "domain": None,      "role": None},
    {"email": "test_revocable_user@example.com",      "password": "ChangeMe123!", "domain": "legal",   "role": "reader"},
]


def get_admin_token() -> str:
    resp = requests.post(
        f"{API_BASE_URL}/auth/token",
        data={"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    if resp.status_code != 200:
        print(f"FAILED to login as admin: {resp.status_code} {resp.text}")
        sys.exit(1)
    print(f"  Logged in as {ADMIN_EMAIL}")
    return resp.json()["access_token"]


def get_domains(token: str) -> dict:
    resp = requests.get(
        f"{API_BASE_URL}/domains/",
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    domains = {d["name"].lower(): d["id"] for d in resp.json()}
    print(f"  Found domains: {list(domains.keys())}")
    return domains


def create_user_in_domain(token: str, email: str, password: str, domain_id: str, role: str):
    resp = requests.post(
        f"{API_BASE_URL}/auth/users",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"email": email, "password": password, "domain_id": domain_id, "role": role},
    )
    if resp.status_code in (200, 201):
        print(f"  OK: {email} → {role} in {domain_id}")
    else:
        print(f"  WARNING: {email} domain={domain_id} → {resp.status_code} {resp.text}")


def create_no_domain_user(token: str, email: str, password: str, domains: dict):
    # POST to create the account — pick first domain just to satisfy the required
    # domain_id field, the test_no_access_user has no meaningful domain access.
    first_domain_id = next(iter(domains.values()))
    resp = requests.post(
        f"{API_BASE_URL}/auth/users",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"email": email, "password": password, "domain_id": first_domain_id, "role": "reader"},
    )
    if resp.status_code in (200, 201):
        print(f"  OK (no-domain user created with placeholder assignment): {email}")
    else:
        print(f"  WARNING: {email} → {resp.status_code} {resp.text}")


def main():
    print("Fetching admin token...")
    token = get_admin_token()

    print("\nFetching domains...")
    domains = get_domains(token)
    if not domains:
        print("No domains found. Create your domains first then re-run.")
        sys.exit(1)

    missing = {"legal", "medical", "computer science"} - set(domains.keys())
    if missing:
        print(f"WARNING: Missing expected domains: {missing}")
        print("Tests referencing those domains will fail. Create them via the API first.")

    print("\nCreating test users...")
    for entry in TEST_USERS:
        email, password, domain_name, role = entry["email"], entry["password"], entry["domain"], entry["role"]
        if domain_name is None:
            create_no_domain_user(token, email, password, domains)
            continue
        domain_id = domains.get(domain_name)
        if not domain_id:
            print(f"  SKIP: domain '{domain_name}' not found — skipping {email}")
            continue
        create_user_in_domain(token, email, password, domain_id, role)

    print("\nDone. Update config.py TEST_USERS usernames to match:")
    print("  single_domain_legal        → test_legal_user@example.com")
    print("  single_domain_medical      → test_medical_user@example.com")
    print("  single_domain_cs           → test_cs_user@example.com")
    print("  multi_domain_legal_medical → test_legal_medical_user@example.com")
    print("  no_domains                 → test_no_access_user@example.com")
    print("  revocable_user             → test_revocable_user@example.com")
    print("\nNOTE: this script only creates ACCOUNTS with role assignments.")
    print("It does NOT seed documents. legal/medical have no documents in the")
    print("corpus yet — you must ingest at least one doc per domain (plus one")
    print("doc tagged to both legal+medical) before union/shared-doc RBAC")
    print("tests can produce meaningful (non-trivially-empty) results.")


if __name__ == "__main__":
    main()