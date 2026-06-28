"""
File storage helper — persists raw uploaded files to local disk so they
can be previewed, downloaded, and cleanly replaced later.

Destination: app/services/storage/file_storage.py

Storage root is configurable via settings.DOCUMENT_STORAGE_ROOT
(default: ./storage/documents).

Disk layout:
    {DOCUMENT_STORAGE_ROOT}/{domain_id}/{document_id}{ext}

Document.file_path stores the path *relative* to DOCUMENT_STORAGE_ROOT
(e.g. "3fa8.../9c12....pdf") so the storage root can be relocated or
reconfigured without a data migration.
"""
from __future__ import annotations

from pathlib import Path
from uuid import UUID

from app.core.config import settings

_EXTENSION_BY_SOURCE_TYPE = {
    "pdf": ".pdf",
    "docx": ".docx",
    "csv": ".csv",
    "xlsx": ".xlsx",
}


def _storage_root() -> Path:
    root = Path(settings.DOCUMENT_STORAGE_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return root


def relative_path_for(domain_id: UUID, document_id: UUID, source_type: str) -> str:
    ext = _EXTENSION_BY_SOURCE_TYPE.get(source_type, "")
    return f"{domain_id}/{document_id}{ext}"


def save_document_file(
    domain_id: UUID, document_id: UUID, source_type: str, file_bytes: bytes
) -> str:
    """Writes file_bytes to disk, returns the relative path to store on Document.file_path."""
    relative_path = relative_path_for(domain_id, document_id, source_type)
    full_path = _storage_root() / relative_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_bytes(file_bytes)
    return relative_path


def resolve_full_path(relative_path: str) -> Path:
    return _storage_root() / relative_path


def delete_document_file(relative_path: str | None) -> None:
    if not relative_path:
        return
    try:
        resolve_full_path(relative_path).unlink(missing_ok=True)
    except OSError:
        pass