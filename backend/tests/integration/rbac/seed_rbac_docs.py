"""
Seed legal/medical/shared documents for RBAC test fixtures.

Uploads .docx files through the real ingestion API at POST /api/v1/ingest/document,
then prints the resulting doc_ids so you can paste them into config.py's SEED_DOCS.

KEY DIFFERENCES FROM THE ORIGINAL SCRIPT:
  - Correct endpoint: POST /api/v1/ingest/document  (not /documents/upload)
  - Single domain_id per upload (UUID, Form field) — the endpoint does NOT
    accept a list. The shared doc is uploaded twice (once per domain).
  - Admin must have 'contributor' access on each domain. If require_domain_access
    blocks the admin, flip USE_DOMAIN_USER_TOKENS = True and ensure the domain
    contributor users exist in Keycloak (test_legal_user@example.com etc.).

Usage:
    python seed_rbac_docs.py
"""

import sys
import time
import requests

API_BASE_URL = "http://localhost:8000/api/v1"
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "changeme123"

# If the admin doesn't have contributor role on domains and uploads 403,
# set this to True and the script will log in as the domain contributor
# users instead (test_legal_user@example.com / ChangeMe123! etc.)
USE_DOMAIN_USER_TOKENS = False
DOMAIN_USER_PASSWORD = "ChangeMe123!"

UPLOAD_PATH = "/ingest/document"

SEED_FILES = [
    {
        "key": "legal_only_doc",
        "path": "seed_docs/legal_only_doc.docx",
        "domains": ["legal"],
        "probe_term": "ZZPROBE-LEGAL-7f3a91",
    },
    {
        "key": "medical_only_doc",
        "path": "seed_docs/medical_only_doc.docx",
        "domains": ["medical"],
        "probe_term": "ZZPROBE-MEDICAL-c4e02d",
    },
    {
        "key": "shared_legal_medical_doc",
        "path": "seed_docs/shared_legal_medical_doc.docx",
        "domains": ["legal", "medical"],   # uploaded once per domain
        "probe_term": "ZZPROBE-SHARED-91bd6a",
    },

    {
        "key": "cs_only_doc",
        "path": "seed_docs/cs_only_doc.docx",
        "domains": ["computer science"],   # uploaded once per domain
        "probe_term": "ZZPROBE-CS-b8f14e",
    }
]


def get_token(email: str, password: str) -> str:
    resp = requests.post(
        f"{API_BASE_URL}/auth/token",
        data={"username": email, "password": password},
    )
    if resp.status_code != 200:
        print(f"  FAILED to login as {email}: {resp.status_code} {resp.text}")
        sys.exit(1)
    print(f"  Logged in as {email}")
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


def upload_document(token: str, file_path: str, domain_id: str, title: str = None):
    """Upload one file to one domain. Returns the response object."""
    headers = {"Authorization": f"Bearer {token}"}
    filename = file_path.split("/")[-1]
    with open(file_path, "rb") as f:
        files = {
            "file": (
                filename,
                f,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        }
        data = {"domain_id": domain_id}
        if title:
            data["title"] = title
        resp = requests.post(
            f"{API_BASE_URL}{UPLOAD_PATH}",
            headers=headers,
            files=files,
            data=data,
        )
    return resp


def main():
    print("Fetching admin token...")
    admin_token = get_token(ADMIN_EMAIL, ADMIN_PASSWORD)

    print("\nFetching domains...")
    domains = get_domains(admin_token)

    missing = {"legal", "medical"} - set(domains.keys())
    if missing:
        print(f"ERROR: missing expected domains: {missing}. Create them first.")
        sys.exit(1)

    # Per-domain tokens if the admin lacks contributor role
    domain_tokens = {}
    if USE_DOMAIN_USER_TOKENS:
        print("\nFetching domain contributor tokens...")
        for domain_name in ["legal", "medical"]:
            email = f"test_{domain_name}_user@example.com"
            domain_tokens[domain_name] = get_token(email, DOMAIN_USER_PASSWORD)

    print("\nUploading seed documents...")
    results = {}

    for entry in SEED_FILES:
        key = entry["key"]
        file_path = entry["path"]
        probe = entry["probe_term"]
        first_doc_id = None

        for domain_name in entry["domains"]:
            domain_id = domains[domain_name]
            token = domain_tokens.get(domain_name, admin_token) if USE_DOMAIN_USER_TOKENS else admin_token

            print(f"\n  Uploading '{key}' -> domain '{domain_name}' ({domain_id})")
            resp = upload_document(token, file_path, domain_id)

            if resp.status_code == 409:
                body = resp.json()
                err = body.get("detail", {})
                if isinstance(err, dict) and err.get("error") == "duplicate_document":
                    doc_id = err.get("existing_document_id")
                    print(f"  Already exists: doc_id = {doc_id} (using existing)")
                    first_doc_id = first_doc_id or doc_id
                    continue
                else:
                    print(f"  409 conflict (not duplicate): {body}")
                    print(f"  -> File may have changed. Delete the old doc or use /ingest/replace.")
                    continue

            if resp.status_code not in (200, 201):
                print(f"  FAILED ({resp.status_code}): {resp.text}")
                if resp.status_code == 403:
                    print(f"  -> Admin may lack 'contributor' role on domain '{domain_name}'.")
                    print(f"     Set USE_DOMAIN_USER_TOKENS = True at the top of this script.")
                elif resp.status_code == 404:
                    print(f"  -> Endpoint not found. Check UPLOAD_PATH = '{UPLOAD_PATH}'")
                    print(f"     and verify the ingest router prefix in ingest.py / main.py.")
                continue

            body = resp.json()
            doc_id = body.get("document_id") or body.get("doc_id") or body.get("id")
            if not doc_id:
                print(f"  WARNING: upload succeeded but no doc_id in response: {body}")
                continue

            print(f"  OK: doc_id = {doc_id}")
            first_doc_id = first_doc_id or doc_id

        if first_doc_id:
            results[key] = (first_doc_id, probe, entry["domains"])

    print("\nWaiting for ingestion pipeline to settle (20s)...")
    time.sleep(20)

    print("\n" + "=" * 70)
    print("Paste these into config.py's SEED_DOCS:")
    print("=" * 70)
    for entry in SEED_FILES:
        key = entry["key"]
        if key in results:
            doc_id, probe, domain_list = results[key]
            print(f'\n  "{key}": {{')
            print(f'      "doc_id": "{doc_id}",')
            print(f'      "domains": {domain_list},')
            print(f'      "unique_probe_term": "{probe}",')
            print(f'      "seeded": True,')
            print(f'  }},')
        else:
            print(f'\n  # "{key}": UPLOAD FAILED — fix errors above and re-run')

    if len(results) < len(SEED_FILES):
        print("\nNOTE: one or more uploads failed. Fix the errors above before updating config.py.")


if __name__ == "__main__":
    main()