"""
backend/app/services/graph/ontology_builder.py

Step 2 of the auto-ontology pipeline (see ontology_loader.py for step 1,
the discovery side). This module only runs on a cache miss: a domain
that has no file under services/graph/ontologies/ yet.

Flow:
    1. Caller (extractor.py) sees domain not in ontology_loader.get_known_domains()
    2. Calls ensure_ontology(domain, sample_texts)
    3. This module takes a Redis lock for that domain (two Celery workers
       hitting a brand-new domain's first two documents at ~the same time
       must not both fire the LLM call and race to write the file — same
       class of bug as the ingest.py FK-violation race, see module history)
    4. Asks the local LLM, once, to propose node_labels + relationship_types
       in the EXACT shape ner_client.py / triple_extractor.py already parse
       (schema_version, node_labels[], relationship_types[])
    5. Validates the JSON structurally before writing anything to disk —
       a malformed file here would break extraction for every future
       document in this domain, not just this one
    6. Writes the file via ontology_loader.get_ontology_path(domain)

After this, ontology_loader.get_known_domains() picks the domain up on
its next call (it re-scans the directory) — no cache to bust, no second
code path to update.

No canonicalization, no drift-prevention, no schema evolution. The
first call's sample text is all the schema will ever be built from for
this domain, same limitation as the hand-written legal/medical files,
just self-inflicted instead of hand-written (per project scope decision).
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.core.config import settings
from app.core.metrics import (
    KNOWN_ONTOLOGY_DOMAINS,
    ONTOLOGY_BUILD_ATTEMPTS_TOTAL,
    ONTOLOGY_BUILD_DURATION_SECONDS,
    ONTOLOGY_BUILD_LOCK_WAIT_SECONDS,
)
from app.services.graph import ontology_loader
from app.services.llm.local_llm import LocalLLMService, LocalLLMTimeoutError

logger = logging.getLogger("ontology_builder")

_LOCK_TTL_SECONDS = 90  # generous; a local LLM JSON proposal call is slow, not 90s slow, but err safe
_MIN_NODE_LABELS = 4
_MIN_RELATIONSHIP_TYPES = 3
_MAX_SAMPLE_CHARS = 6000  # keep the proposal prompt small; this is a schema sketch, not full-text analysis

_llm = LocalLLMService()


class OntologyBuildError(RuntimeError):
    """Raised when the LLM's proposal can't be turned into a usable ontology file."""


# ---------------------------------------------------------------------------
# Cross-document sample accumulation
# ---------------------------------------------------------------------------
# ensure_ontology() (below) builds from whatever sample_texts it's handed,
# with no opinion about where those came from. That's fine in isolation,
# but building from a single document's first few chunks means the schema
# reflects that one document's quirks (its specific examples, its specific
# phrasing) rather than the domain as a whole — there's no way for a model
# to generalize about a domain from n=1 document, however well-prompted.
#
# accumulate_or_build() sits in front of ensure_ontology() as the new entry
# point for the common "domain has no ontology yet" path: each new document
# in an unrecognized domain contributes its sample chunks to a per-domain
# Redis list instead of triggering a build immediately. Only once
# _MIN_SAMPLE_DOCUMENTS documents have contributed does it pull everything
# accumulated and call ensure_ontology with the combined, more
# representative sample set.
#
# Storage is Redis (not Postgres) deliberately: this is transient pipeline
# state that exists only until the threshold is hit and the buffer is
# cleared, not data any other part of the system ever queries relationally
# — the same reasoning that already put the build lock in Redis.
_MIN_SAMPLE_DOCUMENTS = 5


def _sample_buffer_key(domain: str) -> str:
    return f"ontology_sample_buffer:{domain}"


async def accumulate_or_build(domain: str, sample_texts: list[str]) -> bool:
    """
    Call this instead of ensure_ontology() directly from the per-document
    extraction path. Returns True only if THIS call's contribution was the
    one that pushed the domain over _MIN_SAMPLE_DOCUMENTS and a new ontology
    file was actually written. Returns False in every other case —
    including "this document's samples were buffered, nothing built yet"
    and "the domain already has an ontology" — so callers that only care
    about "did building happen" can treat the return value the same way
    ensure_ontology's callers already do.

    Callers that need to distinguish "buffered, not enough yet" from "built
    just now" (extractor.py does, to decide whether to skip graph
    extraction for this document) should check ontology_loader.ontology_exists()
    or get_known_domains() AFTER calling this, not rely on the return value
    alone — that's the actual source of truth and avoids this function
    needing a richer return type just to serve one caller's branching.
    """
    if ontology_loader.ontology_exists(domain):
        return False

    redis_client = _get_redis()
    buffer_key = _sample_buffer_key(domain)
    lock_key = f"ontology_build_lock:{domain}"

    # Append this document's contribution first, unconditionally — even if
    # another worker is mid-build on the lock below, this document's
    # samples should still count toward the NEXT domain that needs
    # buffering, and appending is safe to do without holding the build
    # lock (RPUSH is atomic; we're not reading-then-deciding here).
    if sample_texts:
        await redis_client.rpush(buffer_key, *sample_texts)

    buffered_count = await redis_client.llen(buffer_key)
    # NOTE: this counts SAMPLE CHUNKS pushed, not documents. Each call here
    # is expected to pass one document's worth of chunks (same
    # _ONTOLOGY_SAMPLE_CHUNK_COUNT-sized slice extractor.py already builds
    # today), so document count is tracked separately — see
    # _sample_doc_count_key below — rather than inferring it from chunk
    # count, since documents can contribute different numbers of chunks
    # (e.g. a short document with fewer than 5 chunks total).
    doc_count_key = f"{buffer_key}:doc_count"
    doc_count = await redis_client.incr(doc_count_key)

    if doc_count < _MIN_SAMPLE_DOCUMENTS:
        logger.info(
            "ontology_builder: domain '%s' has no ontology yet — buffered document %d/%d "
            "before a build will be attempted.",
            domain, doc_count, _MIN_SAMPLE_DOCUMENTS,
        )
        return False

    got_lock = await redis_client.set(lock_key, "1", nx=True, ex=_LOCK_TTL_SECONDS)
    if not got_lock:
        # Someone else already hit the threshold and is building right
        # now. Don't pull the buffer out from under them or double-call
        # the LLM — ensure_ontology's own _wait_for_file path (reached via
        # the ensure_ontology call below once we eventually get the lock,
        # or here directly) covers waiting for that build to land.
        logger.info(
            "ontology_builder: domain '%s' hit the sample threshold but the build lock is "
            "already held by another worker — waiting on that build instead.",
            domain,
        )
        await _wait_for_file(domain)
        return False

    try:
        if ontology_loader.ontology_exists(domain):
            return False

        raw_samples = await redis_client.lrange(buffer_key, 0, -1)
        all_samples = [s.decode("utf-8") if isinstance(s, bytes) else s for s in raw_samples]
        logger.info(
            "ontology_builder: domain '%s' reached %d buffered documents — building ontology "
            "from %d accumulated sample chunk(s) across all of them.",
            domain, doc_count, len(all_samples),
        )
    finally:
        # Release the lock we took here before calling ensure_ontology,
        # which takes (and releases) its own lock under the same key —
        # holding both at once would just deadlock against ourselves.
        await redis_client.delete(lock_key)

    built = await ensure_ontology(domain, all_samples)

    if built:
        # Only clear the buffer once a file actually landed on disk. If
        # ensure_ontology raised (LLM timeout, invalid proposal, etc.) the
        # buffer is deliberately left in place — the accumulated samples
        # aren't lost, and the next document's call here will retry the
        # build with the same accumulated set rather than starting over
        # from zero.
        await redis_client.delete(buffer_key)
        await redis_client.delete(doc_count_key)

    return built


async def ensure_ontology(domain: str, sample_texts: list[str]) -> bool:
    """
    Idempotent: if the domain already has a file (written by this call
    or by a concurrent one that won this lock), this is a no-op.

    Returns True if this call built and wrote a new ontology file,
    False if the domain already had one (no LLM call made).
    """
    if ontology_loader.ontology_exists(domain):
        return False

    redis_client = _get_redis()
    lock_key = f"ontology_build_lock:{domain}"

    got_lock = await redis_client.set(lock_key, "1", nx=True, ex=_LOCK_TTL_SECONDS)
    if not got_lock:
        # Someone else is building this domain's ontology right now.
        # Don't double-call the LLM; wait for them to finish and re-check.
        logger.info("ontology_builder: lock held for domain '%s', waiting on the build in progress.", domain)
        await _wait_for_file(domain)
        return False

    try:
        # Re-check after acquiring the lock — covers the gap between the
        # exists() check above and the lock being granted.
        if ontology_loader.ontology_exists(domain):
            return False

        logger.info("ontology_builder: building new ontology for domain '%s' from %d sample doc(s).",
                     domain, len(sample_texts))
        build_start = time.monotonic()
        try:
            proposal = await _propose_ontology(domain, sample_texts)
            proposal = _ensure_baseline_labels(domain, proposal)
            _validate_proposal(domain, proposal)
            await _validate_domain_relevance(domain, sample_texts, proposal)
        except OntologyBuildError as exc:
            outcome = "llm_timeout" if "timed out" in str(exc) else (
                "llm_invalid_json" if "valid JSON" in str(exc) else (
                    "domain_mismatch" if "does not appear to match" in str(exc) else "validation_failed"
                )
            )
            ONTOLOGY_BUILD_ATTEMPTS_TOTAL.labels(domain=domain, outcome=outcome).inc()
            ONTOLOGY_BUILD_DURATION_SECONDS.labels(domain=domain).observe(time.monotonic() - build_start)
            raise

        path = ontology_loader.get_ontology_path(domain)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(proposal, f, indent=2, ensure_ascii=False)

        ONTOLOGY_BUILD_ATTEMPTS_TOTAL.labels(domain=domain, outcome="success").inc()
        ONTOLOGY_BUILD_DURATION_SECONDS.labels(domain=domain).observe(time.monotonic() - build_start)
        KNOWN_ONTOLOGY_DOMAINS.set(len(ontology_loader.get_known_domains()))

        logger.info(
            "ontology_builder: wrote new ontology for domain '%s' (%d node_labels, %d relationship_types) to %s",
            domain, len(proposal["node_labels"]), len(proposal["relationship_types"]), path,
        )
        return True

    finally:
        await redis_client.delete(lock_key)


async def _wait_for_file(domain: str, timeout_seconds: float = 60.0, poll_seconds: float = 1.0) -> None:
    """Poll for the file another worker is building, instead of returning
    immediately and letting the caller hit a FileNotFoundError a moment later."""
    import asyncio
    start = time.monotonic()
    waited = 0.0
    while waited < timeout_seconds:
        if ontology_loader.ontology_exists(domain):
            ONTOLOGY_BUILD_LOCK_WAIT_SECONDS.labels(domain=domain).observe(time.monotonic() - start)
            return
        await asyncio.sleep(poll_seconds)
        waited += poll_seconds
    ONTOLOGY_BUILD_LOCK_WAIT_SECONDS.labels(domain=domain).observe(time.monotonic() - start)
    logger.warning(
        "ontology_builder: timed out waiting for concurrent build of domain '%s' "
        "after %.0fs — proceeding, caller's own ontology load will raise if it's still missing.",
        domain, timeout_seconds,
    )


def _get_redis():
    """
    Thin wrapper so this module's import doesn't hard-fail if redis.asyncio
    isn't installed in some environment — fails loudly only when actually
    called, with a clear message, rather than at import time for every
    module that imports ontology_builder.
    """
    import redis.asyncio as redis

    redis_url = (
        getattr(settings, "REDIS_URL", None)
        or getattr(settings, "CELERY_BROKER_URL", None)
        or getattr(settings, "CELERY_RESULT_BACKEND", None)
    )
    if not redis_url:
        raise OntologyBuildError(
            "No Redis URL found on settings (checked REDIS_URL, CELERY_BROKER_URL, "
            "CELERY_RESULT_BACKEND). Set one of these or hardcode the right attribute "
            "name in ontology_builder._get_redis()."
        )
    return redis.from_url(redis_url)


# ---------------------------------------------------------------------------
# LLM proposal
# ---------------------------------------------------------------------------
def _build_prompt(domain: str, sample_texts: list[str]) -> str:
    joined = "\n\n---\n\n".join(
        text[:_MAX_SAMPLE_CHARS] for text in sample_texts if text and text.strip()
    )
    joined = joined[: _MAX_SAMPLE_CHARS]  # hard cap even across multiple samples

    return f"""You are designing a knowledge-graph ontology for a new document domain: "{domain}".

Below are sample excerpts from real documents in this domain:

{joined}

Note: "DocumentTitle" and "Author" labels, plus the relationship between them, are added automatically after your proposal — you do NOT need to include them yourself. Focus your node_labels on domain-specific concepts instead (e.g. algorithms, diseases, laws, datasets, tools) and the peripheral entities specific to this domain beyond title/author (e.g. course names, dates, organizations).

Your goal is to produce a JSON ontology schema that will be used in two ways:
1. A zero-shot NER model (GLiNER) will be given each label's "label" field, automatically converted from PascalCase into a lowercase phrase by splitting on capital letters (e.g. "MachineLearningAlgorithm" -> "machine learning algorithm", "AuthorEntity" -> "author entity"). THIS converted phrase — not the "description" field — is what GLiNER actually matches against text. The "description" field is for human/documentation purposes only and is never sent to the NER model. This means the "label" name itself must already read as a natural noun phrase once split and lowercased, because that is the literal string GLiNER will try to match.
2. A local LLM will use the relationship_types to extract triples. "from" is the subject entity type (the one performing or being the primary actor), "to" is the object entity type.

Label design rules:
- Include 7-10 node labels. Cover BOTH the core domain concepts (e.g. algorithms, diseases, laws) AND the peripheral entities that actually appear in text (e.g. authors, tools, course names, document titles, dates). Documents mention peripheral entities far more often than core ones.
- Generalize, don't enumerate: when the sample text lists several specific examples of one underlying concept (e.g. "ML is used in fraud detection, facial recognition, and speech transcription" is three examples of one thing — applications/tasks), create ONE label for the general category, not one label per example. A label should represent a category this domain has MANY instances of, not one specific instance the sample happened to mention in passing. Before adding a label, ask: "will many different real entities map to this label across many documents, or did I just name one thing I saw once?" If the latter, fold it into a more general label instead.
- PascalCase label names (used as graph node labels — no spaces). Critically, avoid generic suffix words like "Entity", "Type", "Object", "Item", or "Concept" tacked onto a label — they survive into the GLiNER-facing phrase as noise that weakens the semantic match. Prefer "Author" over "AuthorEntity", "Task" over "TaskType", "Publication" over "PublicationType". A suffix is fine only when it's a concrete, meaningful part of the concept rather than a generic wrapper — "DocumentTitle" is fine because "title" is specific, but "DocumentEntity" would not be.
- Self-test before finalizing each label: split it on capital letters and lowercase it (mentally apply the same transform GLiNER will see), then ask "would a person use this exact phrase to describe this entity out loud?" If the answer is no — if it sounds like an identifier rather than a phrase — rename the label.
- Each label's "description" must still be a short natural-language phrase a human would use to describe that thing in a sentence, starting with "a" or "the" (e.g. "a machine learning algorithm or model"). This is for documentation/downstream use, not for the NER model.

Relationship design rules:
- At least 4 relationship_types.
- "from" is the SUBJECT (the entity that performs, is, or has the relationship). "to" is the OBJECT.
- Example: if a DocumentTitle is AUTHORED_BY an Author, then from="DocumentTitle", to="Author" — the document is the subject, the author is the object.
- "from" and "to" must each be a label you defined in node_labels.
- Predicate must be a single UPPER_SNAKE_CASE token.
- Include a "meaning" field: one sentence describing what the relationship means, with subject and object named explicitly (e.g. "The document was written by the author").

Respond with ONLY a JSON object, no preamble, no markdown fences, no explanation:

{{
  "ontology": "{domain.title()} Domain Ontology",
  "schema_version": "v1.0",
  "node_labels": [
    {{
      "label": "PascalCaseEntityType",
      "description": "a short natural-language phrase describing what this entity is",
      "key_properties": ["name", "domain", "schema_version", "source_chunk_ids"]
    }}
  ],
  "relationship_types": [
    {{
      "relationship": "UPPER_SNAKE_CASE_PREDICATE",
      "from": "SubjectEntityLabel",
      "to": "ObjectEntityLabel",
      "meaning": "The subject was/is/does X to the object."
    }}
  ]
}}

key_properties must always be exactly ["name", "domain", "schema_version", "source_chunk_ids"] for every node label.
"""


async def _propose_ontology(domain: str, sample_texts: list[str]) -> dict[str, Any]:
    prompt = _build_prompt(domain, sample_texts)
    try:
        raw = await _llm.generate(prompt)
    except LocalLLMTimeoutError as exc:
        raise OntologyBuildError(f"LLM timed out proposing ontology for domain '{domain}': {exc}") from exc

    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OntologyBuildError(
            f"LLM ontology proposal for domain '{domain}' was not valid JSON: {exc}. Raw: {raw[:500]}"
        ) from exc

    return parsed


# ---------------------------------------------------------------------------
# Baseline labels — guaranteed regardless of what the LLM proposed
# ---------------------------------------------------------------------------
# Title and author are structural metadata almost every document has, but
# whether the LLM's proposal includes them depends entirely on whether the
# small sample of chunks it was shown happened to surface a byline near the
# top. A document whose first 5 chunks are all body text (no visible title
# page) would otherwise build a domain ontology with no way to ever capture
# "who wrote this" for ANY future document in that domain, since labels are
# frozen after this one build (see module docstring). Rather than leaving
# that to chance, this guarantees the two labels and their relationship
# exist, then lets the LLM's domain-specific labels add everything else on
# top. This runs before _validate_proposal so the injected entries get the
# same structural checks as everything the LLM proposed.
_BASELINE_TITLE_LABEL = "DocumentTitle"
_BASELINE_TITLE_DESCRIPTION = "the title of a document"
_BASELINE_AUTHOR_LABEL = "Author"
_BASELINE_AUTHOR_DESCRIPTION = "the name of a person who wrote or created a document"
_BASELINE_RELATIONSHIP = "AUTHORED_BY"

# Phrases that suggest an existing label already plays the "title" or
# "author" role under a different name (e.g. the LLM called it "Paper" or
# "Creator") — checked against both the label (humanized the same way
# ner_client.py does) and the description, so a same-meaning label proposed
# under different wording isn't duplicated alongside the baseline one.
_TITLE_ROLE_HINTS = ("title", "paper", "publication name", "document name")
_AUTHOR_ROLE_HINTS = ("author", "writer", "creator", "wrote", "created by")

# Local copy of the PascalCase->phrase split also used in ner_client.py.
# Not imported from there on purpose: ontology generation is upstream of
# NER (ner_client.py reads the files this module writes), so depending on
# ner_client.py here would invert that layering for the sake of one tiny
# regex. Keep both in sync if the splitting rule ever changes.
import re as _re
_BASELINE_PASCAL_SPLIT_RE = _re.compile(r"(?<!^)(?=[A-Z])")


def _humanize_for_role_check(label: str) -> str:
    return " ".join(_BASELINE_PASCAL_SPLIT_RE.split(label)).lower()


def _label_matches_role(entry: dict[str, Any], hints: tuple[str, ...]) -> bool:
    haystack = f"{_humanize_for_role_check(entry.get('label', ''))} {entry.get('description', '')}".lower()
    return any(hint in haystack for hint in hints)


def _ensure_baseline_labels(domain: str, proposal: dict[str, Any]) -> dict[str, Any]:
    node_labels = proposal.get("node_labels")
    if not isinstance(node_labels, list):
        # Malformed shape — let _validate_proposal raise its own clear error
        # rather than this function trying to patch something unparseable.
        return proposal

    has_title = any(_label_matches_role(e, _TITLE_ROLE_HINTS) for e in node_labels if isinstance(e, dict))
    has_author = any(_label_matches_role(e, _AUTHOR_ROLE_HINTS) for e in node_labels if isinstance(e, dict))

    title_label = _BASELINE_TITLE_LABEL
    author_label = _BASELINE_AUTHOR_LABEL

    if not has_title:
        node_labels.append({
            "label": _BASELINE_TITLE_LABEL,
            "description": _BASELINE_TITLE_DESCRIPTION,
            "key_properties": ["name", "domain", "schema_version", "source_chunk_ids"],
        })
        logger.info("ontology_builder: domain '%s' proposal had no title-like label — added baseline '%s'.",
                     domain, _BASELINE_TITLE_LABEL)
    else:
        # Use whatever label the LLM actually proposed for this role, so the
        # baseline relationship below points at the real label name instead
        # of creating a duplicate "DocumentTitle" the LLM's own label shadows.
        title_label = next(e["label"] for e in node_labels if isinstance(e, dict) and _label_matches_role(e, _TITLE_ROLE_HINTS))

    if not has_author:
        node_labels.append({
            "label": _BASELINE_AUTHOR_LABEL,
            "description": _BASELINE_AUTHOR_DESCRIPTION,
            "key_properties": ["name", "domain", "schema_version", "source_chunk_ids"],
        })
        logger.info("ontology_builder: domain '%s' proposal had no author-like label — added baseline '%s'.",
                     domain, _BASELINE_AUTHOR_LABEL)
    else:
        author_label = next(e["label"] for e in node_labels if isinstance(e, dict) and _label_matches_role(e, _AUTHOR_ROLE_HINTS))

    relationship_types = proposal.get("relationship_types")
    if isinstance(relationship_types, list):
        has_authored_by = any(
            isinstance(r, dict) and r.get("from") == title_label and r.get("to") == author_label
            for r in relationship_types
        )
        if not has_authored_by:
            relationship_types.append({
                "relationship": _BASELINE_RELATIONSHIP,
                "from": title_label,
                "to": author_label,
                "meaning": "The document was written by the author.",
            })
            logger.info("ontology_builder: domain '%s' proposal had no title-author relationship — added baseline '%s' (%s -> %s).",
                         domain, _BASELINE_RELATIONSHIP, title_label, author_label)

    return proposal


# ---------------------------------------------------------------------------
# Validation — must pass before anything touches disk
# ---------------------------------------------------------------------------
def _validate_proposal(domain: str, proposal: Any) -> None:
    if not isinstance(proposal, dict):
        raise OntologyBuildError(f"Ontology proposal for '{domain}' is not a JSON object.")

    if not proposal.get("schema_version"):
        raise OntologyBuildError(f"Ontology proposal for '{domain}' is missing 'schema_version'.")

    node_labels = proposal.get("node_labels")
    if not isinstance(node_labels, list) or len(node_labels) < _MIN_NODE_LABELS:
        raise OntologyBuildError(
            f"Ontology proposal for '{domain}' has fewer than {_MIN_NODE_LABELS} node_labels."
        )

    label_names: set[str] = set()
    for entry in node_labels:
        if not isinstance(entry, dict) or not entry.get("label"):
            raise OntologyBuildError(f"Ontology proposal for '{domain}' has a malformed node_labels entry: {entry!r}")
        label_names.add(entry["label"])

    relationship_types = proposal.get("relationship_types")
    if not isinstance(relationship_types, list) or len(relationship_types) < _MIN_RELATIONSHIP_TYPES:
        raise OntologyBuildError(
            f"Ontology proposal for '{domain}' has fewer than {_MIN_RELATIONSHIP_TYPES} relationship_types."
        )

    for rel in relationship_types:
        if not isinstance(rel, dict) or not rel.get("relationship") or not rel.get("from") or not rel.get("to"):
            raise OntologyBuildError(f"Ontology proposal for '{domain}' has a malformed relationship entry: {rel!r}")
        if rel["from"] not in label_names or rel["to"] not in label_names:
            raise OntologyBuildError(
                f"Ontology proposal for '{domain}': relationship {rel['relationship']!r} references "
                f"a from/to label not present in node_labels ({rel['from']!r} -> {rel['to']!r})."
            )


# ---------------------------------------------------------------------------
# Domain-relevance sanity check
# ---------------------------------------------------------------------------
# This exists because of a real incident: a document was ingested under a
# domain_id named "computer science", but the document's own content was
# medical (oncology). _propose_ontology faithfully built a schema from
# what it was given — Physician/Tumor/MammogramResult — and _validate_proposal
# happily passed it, because structurally it WAS a valid ontology. It just
# had nothing to do with the domain name it got filed under. Once written,
# that file is permanent (see module docstring) and silently breaks every
# real document in that domain afterward (NER returns empty entity lists
# with no obvious error — see ner_client debug logs).
#
# This check can't catch a mis-tagged domain_id itself (that's an
# ingestion-side bug, not this module's to fix), but it can catch the
# downstream symptom: a proposal whose own content doesn't plausibly
# relate to the domain name it's about to be filed under. Cheap, fuzzy,
# and deliberately conservative — false negatives (lets a bad one through)
# are far less costly than false positives (blocks a legitimate domain),
# so on any ambiguity this lets the build proceed and just logs a warning.
_RELEVANCE_PROMPT = """You will be shown a domain name and a proposed list of entity types for a knowledge graph ontology in that domain.

Domain name: "{domain}"

Proposed entity types: {labels}

Does this list of entity types plausibly belong to the domain "{domain}"? A reasonable subject-matter expert would expect ontology entities for "{domain}" to look roughly like this list, even if not an exact match.

Respond with ONLY one word: "yes" or "no"."""


async def _validate_domain_relevance(
    domain: str, sample_texts: list[str], proposal: dict[str, Any]
) -> None:
    labels = [entry["label"] for entry in proposal.get("node_labels", [])]
    prompt = _RELEVANCE_PROMPT.format(domain=domain, labels=", ".join(labels))

    try:
        raw = await _llm.generate(prompt)
    except LocalLLMTimeoutError:
        # Don't fail the whole build over a sanity-check timeout — log
        # and let it through; this check is a safety net, not a gate
        # the core pipeline should be blocked by if the LLM is slow.
        logger.warning(
            "ontology_builder: domain-relevance check timed out for '%s' — proceeding without it.",
            domain,
        )
        return

    answer = raw.strip().lower()
    if answer.startswith("yes"):
        return
    if answer.startswith("no"):
        raise OntologyBuildError(
            f"Ontology proposal for domain '{domain}' does not appear to match the domain name "
            f"(proposed labels: {labels!r}). This usually means the document that triggered this "
            f"build was ingested under the wrong domain_id — check which document supplied "
            f"sample_texts for this build, not the ontology_builder prompt itself."
        )
    # Ambiguous/garbled response from the relevance check itself — don't
    # block a legitimate domain over a flaky one-word classifier reply.
    logger.warning(
        "ontology_builder: domain-relevance check for '%s' returned an unrecognized answer (%r) — "
        "proceeding without blocking.",
        domain, raw[:200],
    )