"""
backend/app/services/graph/ontology_loader.py

Single source of truth for "which domains have an ontology file, and
where is it". Replaces the two independent hardcoded _ONTOLOGY_FILES
dicts that used to live in ner_client.py and triple_extractor.py.

Why this exists: those two dicts had to be edited by hand every time a
new domain's ontology file was added. That's exactly the "manual work
per domain" the ontology-builder pipeline is trying to eliminate — a
new domain's JSON file could exist on disk and still be invisible to
the rest of the system until someone updated two dict literals. This
module discovers domains by scanning the ontologies/ folder instead.

Naming convention (must match ontology_builder.py's writer):
    <domain_key>_ontology_schema.json

Both ner_client.py and triple_extractor.py should import
get_known_domains() / get_ontology_path() from here instead of keeping
their own copies. The label-list and relationship-list parsing stays
in each of those modules (they need different slices of the same file),
only the *discovery* of which files exist is shared.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("ontology_loader")

# backend/app/services/graph/ontologies/
# __file__ is backend/app/services/graph/ontology_loader.py -> parent is services/graph
ONTOLOGY_DIR = Path(__file__).resolve().parent / "ontologies"
_SUFFIX = "_ontology_schema.json"


def _domain_key_from_path(path: Path) -> str:
    return path.name[: -len(_SUFFIX)]


def get_known_domains() -> frozenset[str]:
    """
    Authoritative set of domain keys that currently have an ontology
    file on disk. Re-scans the directory every call (cheap — it's a
    single os.listdir-equivalent over a handful of small JSON files,
    and this is only called once per document at extraction time, not
    per chunk), so a file written by ontology_builder.py mid-run is
    visible immediately without needing a cache-bust call.
    """
    if not ONTOLOGY_DIR.exists():
        return frozenset()
    return frozenset(
        _domain_key_from_path(path)
        for path in ONTOLOGY_DIR.glob(f"*{_SUFFIX}")
    )


def get_ontology_path(domain: str) -> Path:
    """Path an ontology file for `domain` would live at, whether or not
    it exists yet. ontology_builder.py writes here; ner_client.py and
    triple_extractor.py read from here."""
    return ONTOLOGY_DIR / f"{domain}{_SUFFIX}"


def ontology_exists(domain: str) -> bool:
    return get_ontology_path(domain).exists()