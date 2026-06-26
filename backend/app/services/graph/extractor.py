"""
backend/app/services/graph/extractor.py

Phase 5 — Ingestion-time extraction.

Turns a document's already-ingested chunks into graph nodes/edges. Called
by the Celery task `run_entity_extraction` (see app/workers/tasks.py):

    extractor = GraphExtractor()
    asyncio.run(extractor.extract_and_store(document_id, domain_id))

Design notes (see NER_KG_Implementation_Roadmap.md Phase 5 for full context):

- Chunks are read via a SYNC SessionLocal query against ChunkModel, matching
  how app.services.ingestion.document_processor.DocumentProcessor actually
  writes them (sync SQLAlchemy). This is the live ingestion path —
  app.repositories.document_repository.ChunkRepository (async) is NOT used
  anywhere in the real Celery flow and is intentionally not touched here.

- ner_client.extract_entities() and age_client are both async; this module
  is async throughout and gets run via asyncio.run() by the Celery task,
  same pattern as run_entity_extraction already uses today.

- Node identity = (name, domain), MERGE'd — same pattern as
  scripts/ontology_seed.cypher, so runtime-extracted entities merge
  cleanly with pre-seeded ontology nodes instead of duplicating them.
  Each node also gets `schema_version` set (matches key_properties in
  both ontology JSON files), so Phase 8 re-extraction can detect stale
  nodes against the domain's current ontology version.

- Each node gets a `node_uuid` property, minted once via coalesce() on
  first MERGE. This is what gets written back to Chunk.graph_node_ids
  (a Postgres ARRAY(UUID) column — confirmed in app/models/db/models.py).
  AGE's own internal integer node id is NOT used for this, since it's
  not a UUID and isn't guaranteed stable across graph maintenance ops.

- source_chunk_ids on each node is appended-to, not overwritten, since
  the same entity will appear across many chunks/documents over time.

- Relationships: PATCHED — co-occurring entities are no longer connected
  with a generic MENTIONED_WITH edge. Instead, app.services.llm.triple_extractor
  is called per chunk with that chunk's text + NER entities, returning
  typed Subject->Predicate->Object triples already validated against the
  domain's closed ontology relationship_types (predicate AND from/to
  entity-label checks — see triple_extractor.py docstring). Triples that
  fail validation are dropped and logged there, not here. A chunk that
  yields zero valid triples simply gets no relationship edges — this is
  the correct, honest outcome, not a fallback case.

- All AGE writes for one document run inside a single age_client
  transaction, so a failure partway through doesn't leave a half-written
  document in the graph.

- NEW-DOMAIN ONTOLOGY AUTO-BUILD (added alongside the ontology_loader /
  ontology_builder refactor): before _resolve_domain_name's strict check
  (below) is allowed to raise on an unrecognized domain, extract_and_store
  now checks ontology_loader.get_known_domains() itself and, on a miss,
  calls ontology_builder.ensure_ontology() with this document's own
  chunks as the sample text. That call proposes a schema via the local
  LLM, validates it, and writes a new `<key>_ontology_schema.json` under
  services/graph/ontologies/ — after which the existing strict resolve
  below succeeds normally, with zero other change to this module's
  control flow. If the build fails for any reason (LLM timeout, invalid
  JSON, failed validation), ensure_ontology raises OntologyBuildError,
  which is deliberately NOT caught here — same fail-loud philosophy as
  _resolve_domain_name's existing ValueError, this should abort the
  document's extraction and surface clearly rather than silently
  extracting against no ontology at all.

- REQUIRED ONE-TIME (AND ONE-TIME-PER-NEW-LABEL) DDL — node_uuid lookup
  speedup: _merge_typed_relationships below does `MATCH (a {node_uuid:
  $x})` with no label, since node_uuid is meant to be globally unique
  across all labels/domains. This is a MATCH-PATTERN property filter,
  which AGE compiles to a `properties @> agtype_build_map(...)`
  containment check — satisfied by a GIN index on the whole `properties`
  column, NOT a btree on one extracted key (that combination only
  speeds up WHERE-clause filters, a different Cypher syntax). AGE also
  stores each vertex LABEL in its own child table under the graph's
  schema (e.g. rag_ontology."Disease", rag_ontology."Drug" — NOT one
  shared table), so this needs a GIN index on EVERY per-label table,
  not a single statement on a parent table.
  Run scripts/index_node_uuid.py after scripts/seed_graph.py, and again
  any time a new vertex label is introduced (Phase 8 ontology updates,
  OR a brand-new domain's first auto-built ontology — same requirement,
  same script): it discovers every existing label from AGE's own catalog
  and indexes each one, idempotently. See that script's docstring for
  the full reasoning, including two earlier wrong approaches it had to
  rule out along the way — this is schema-maintenance DDL, not
  per-document data, so it does not belong inside this module or inside
  the Celery task that calls it.
"""
from __future__ import annotations

import logging
from uuid import UUID, uuid4

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.db.models import Chunk as ChunkModel
from app.services.graph import age_client, ontology_builder, ontology_loader
from app.services.llm import triple_extractor
from app.services.llm.triple_extractor import CandidateEntity
from app.services.ner import ner_client

logger = logging.getLogger("graph_extractor")

_NER_THRESHOLD = 0.4

# How many chunks from a brand-new domain's first document to hand the
# LLM as ontology-proposal sample text. Kept small and separate from
# extraction proper — this is a one-time schema sketch, not full-document
# analysis, see ontology_builder.py for the prompt itself.
_ONTOLOGY_SAMPLE_CHUNK_COUNT = 5


class GraphExtractor:
    """
    Entry point used by the Celery task. Method signature
    (document_id, domain_id) is fixed by app/workers/tasks.py.
    """

    async def extract_and_store(self, document_id: str, domain_id: str) -> None:
        chunks = self._fetch_chunks(document_id)
        if not chunks:
            logger.info("document_id=%s: no chunks found, nothing to extract.", document_id)
            return

        await self._ensure_domain_ontology(domain_id, chunks)

        domain = self._resolve_domain_name(domain_id, chunks)
        schema_version = ner_client.get_domain_schema_version(domain)
        logger.info(
            "document_id=%s: extracting graph entities for %d chunks (domain=%s, schema_version=%s)",
            document_id, len(chunks), domain, schema_version,
        )

        # chunk.id -> list[node_uuid] written back to Postgres at the end.
        # Built up across the whole document so one Chunk update per chunk,
        # not one per entity.
        chunk_node_links: dict[UUID, list[UUID]] = {chunk.id: [] for chunk in chunks}

        async with age_client.transaction(settings.AGE_GRAPH_NAME) as tx:
            for chunk in chunks:
                # DELIBERATE DESIGN CHOICE, not an oversight: a NER-service
                # failure here is NOT caught and skipped per-chunk. By the
                # time this raises, ner_client.extract_entities() has
                # already exhausted its own bounded retries (see
                # ner_client.py's _MAX_RETRIES) — so this only fires when
                # the NER service has been unreachable across multiple
                # attempts, which is a real outage signal, not a blip.
                # Letting it propagate aborts this whole document's
                # transaction (rolled back by age_client.transaction's
                # except clause below), which is the right call: an
                # outage partway through a document would otherwise leave
                # some chunks with entities and graph nodes and others
                # silently without, with no record of which chunks were
                # actually attempted. The Celery task (run_entity_extraction)
                # is expected to retry the whole document later, the same
                # way it already would for any other unhandled exception
                # here — this comment exists so that expectation is
                # explicit instead of implicit.
                entities = await ner_client.extract_entities(
                    text=chunk.content,
                    domain=domain,
                    threshold=_NER_THRESHOLD,
                )
                if not entities:
                    continue

                # MERGE each entity, keep a name->node_uuid map for this
                # chunk so triples (which reference entities by their
                # original text) can be resolved to node_uuids below.
                node_uuid_by_name: dict[str, UUID] = {}
                for entity in entities:
                    node_uuid = await self._merge_entity_node(
                        tx=tx,
                        label=entity.label,
                        name=entity.text,
                        domain=domain,
                        schema_version=schema_version,
                        chunk_id=chunk.id,
                    )
                    node_uuid_by_name[entity.text] = node_uuid
                    chunk_node_links[chunk.id].append(node_uuid)

                # Typed relation extraction (replaces generic MENTIONED_WITH).
                # Pass this chunk's NER entities as the closed candidate
                # pool — the LLM may only relate entities GLiNER already
                # found, never invent new ones.
                candidate_entities = [
                    CandidateEntity(text=e.text, label=e.label) for e in entities
                ]
                triples = await triple_extractor.extract_triples(
                    chunk_text=chunk.content,
                    entities=candidate_entities,
                    domain=domain,
                )
                if triples:
                    await self._merge_typed_relationships(tx, triples, node_uuid_by_name)

        # Reverse link: write graph_node_ids back onto each chunk in Postgres.
        # Done after the AGE transaction commits, so we never record a link
        # to a node that didn't actually get persisted.
        self._write_chunk_graph_links(chunk_node_links)

        logger.info("document_id=%s: extraction complete.", document_id)

    # ------------------------------------------------------------------
    # New-domain ontology auto-build
    # ------------------------------------------------------------------

    @staticmethod
    async def _ensure_domain_ontology(domain_id: str, chunks: list[ChunkModel]) -> None:
        """
        Runs before _resolve_domain_name's strict check. Guesses the
        ontology key the same way _resolve_domain_name does (display
        name, lowercased/stripped) — duplicating that one line rather
        than refactoring _resolve_domain_name's signature, so its
        existing strict behavior for every other caller is untouched.

        On a miss (key not in ontology_loader.get_known_domains()),
        hands ontology_builder this document's own first few chunks as
        sample text and lets it build + write the ontology file. After
        this returns, _resolve_domain_name's own lookup of
        ner_client.get_known_domains() (which now reads through to the
        same on-disk scan) will see the new file and succeed normally —
        no other code path changes.

        Deliberately does not catch ontology_builder.OntologyBuildError:
        if the LLM proposal fails or produces an invalid schema, this
        document's extraction should abort loudly here, not silently
        fall through to _resolve_domain_name's ValueError with no
        context about why the domain is still unknown.
        """
        with SessionLocal() as db:
            from sqlalchemy import select
            from app.models.db.models import Domain as DomainModel
            domain_uuid = UUID(domain_id)
            domain = db.execute(
                select(DomainModel).where(DomainModel.id == domain_uuid)
            ).scalar_one_or_none()
        if domain is None:
            # Let _resolve_domain_name raise its own clear "not found" error
            # right after this returns, rather than duplicating that check.
            return

        guessed_key = domain.name.strip().lower()
        if guessed_key in ontology_loader.get_known_domains():
            return

        sample_texts = [c.content for c in chunks[:_ONTOLOGY_SAMPLE_CHUNK_COUNT]]
        logger.info(
            "domain_id=%s (name=%r): no ontology file for key %r yet — "
            "building one from this document's first %d chunk(s).",
            domain_id, domain.name, guessed_key, len(sample_texts),
        )
        await ontology_builder.ensure_ontology(guessed_key, sample_texts)

    # ------------------------------------------------------------------
    # Chunk fetching (sync — matches document_processor.py's write path)
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_chunks(document_id: str) -> list[ChunkModel]:
        doc_uuid = UUID(document_id)
        with SessionLocal() as db:
            from sqlalchemy import select
            rows = db.execute(
                select(ChunkModel)
                .where(ChunkModel.document_id == doc_uuid)
                .order_by(ChunkModel.chunk_index)
            ).scalars().all()
            return list(rows)

    @staticmethod
    def _resolve_domain_name(domain_id: str, chunks: list[ChunkModel]) -> str:
        """
        ner_client.extract_entities() and the ontology files key off a
        domain NAME ("medical" / "legal"), not the domain's UUID. Look it
        up from the Domain table once per document rather than per chunk.

        ROOT-CAUSE FIX: Domain.name is the admin-facing display name
        (e.g. "Medical Records"), which is NOT guaranteed to match an
        ontology key ("medical") just by lowercasing it. Previously this
        method returned domain.name.lower() unconditionally — if those
        ever diverged (a domain admin names a domain "Medical Records"
        or "Healthcare" instead of "medical"), the result is either an
        opaque ValueError several calls later from inside ner_client/
        triple_extractor (best case), or, if the lowercased guess happens
        to collide with an unrelated-but-valid key, silently extracting
        against the WRONG domain's ontology (worst case, and the one that
        doesn't announce itself).

        Fix: resolve against the actual set of known ontology domains
        (the same set ner_client.py / triple_extractor.py load from) and
        fail loudly, here, with the exact domain_id/display-name/guessed-
        key all named in the error — not three frames deep in a different
        module with no context about which document or domain triggered it.

        NOTE: as of the ontology auto-build addition, extract_and_store
        calls _ensure_domain_ontology() before this method, which already
        builds a missing ontology file for the common new-domain case. So
        in practice this should now only ever raise for a genuine
        display-name mismatch (e.g. a typo, or a Domain that was never
        meant to have an ontology) — not for "domain is simply new", which
        _ensure_domain_ontology already handles.

        This still doesn't replace a real mapping table if your Domain
        model ever needs admin-chosen domain names that don't resemble
        the ontology key at all (e.g. "Patient Records 2026" -> "medical").
        If that's a real requirement, add an explicit `ontology_key`
        column to the Domain model and read that instead of guessing from
        `name` — this fix makes the *current* guess-from-name approach
        safe to run (fails clearly instead of silently), it doesn't
        remove the underlying assumption that display name ≈ ontology key.
        """
        domain_uuid = UUID(domain_id)
        with SessionLocal() as db:
            from sqlalchemy import select
            from app.models.db.models import Domain as DomainModel
            domain = db.execute(
                select(DomainModel).where(DomainModel.id == domain_uuid)
            ).scalar_one_or_none()
        if domain is None:
            raise ValueError(f"Domain {domain_id} not found")

        guessed_key = domain.name.strip().lower()
        known_domains = ner_client.get_known_domains()
        if guessed_key not in known_domains:
            raise ValueError(
                f"Domain {domain_id} (display name {domain.name!r}) does not match "
                f"any known ontology domain after normalization (got {guessed_key!r}, "
                f"known: {sorted(known_domains)}). This document's domain must be "
                f"renamed to match an ontology key exactly, or a real "
                f"display-name -> ontology-key mapping must be added to the Domain "
                f"model — guessing is not safe here, see _resolve_domain_name docstring."
            )
        return guessed_key

    # ------------------------------------------------------------------
    # Node MERGE
    # ------------------------------------------------------------------

    @staticmethod
    async def _merge_entity_node(
        tx: age_client.GraphTransaction,
        label: str,
        name: str,
        domain: str,
        schema_version: str,
        chunk_id: UUID,
    ) -> UUID:
        """
        MERGE a node keyed on (name, domain), same identity pattern as
        ontology_seed.cypher. Mints node_uuid once (coalesce — only set
        if not already present), stamps the domain's current
        schema_version on every MERGE (overwritten each time, unlike
        node_uuid — Phase 8 needs this to always reflect the version this
        node was last touched under), and appends chunk_id to
        source_chunk_ids without duplicating it.

        Returns the node's node_uuid (existing or newly minted) so the
        caller can resolve triple subject/object text to node_uuids and
        build the chunk reverse-link.
        """
        new_uuid = str(uuid4())
        chunk_id_str = str(chunk_id)

        # AGE Cypher: coalesce() picks the first non-null value, so
        # node_uuid is only set on first MERGE of this entity.
        # schema_version is set unconditionally (not coalesced) — it
        # should always reflect the most recent extraction pass.
        # source_chunk_ids: append chunk_id only if not already present —
        # AGE doesn't have a native "list contains" SET shortcut, so this
        # uses a CASE expression to stay idempotent (re-running extraction
        # on the same chunk doesn't grow the list unbounded).
        cypher = f"""
        MERGE (n:{label} {{name: $name, domain: $domain}})
        SET n.node_uuid = coalesce(n.node_uuid, $new_uuid)
        SET n.schema_version = $schema_version
        SET n.source_chunk_ids = CASE
            WHEN n.source_chunk_ids IS NULL THEN [$chunk_id]
            WHEN $chunk_id IN n.source_chunk_ids THEN n.source_chunk_ids
            ELSE n.source_chunk_ids + [$chunk_id]
        END
        RETURN n.node_uuid AS node_uuid
        """
        rows = await tx.run(
            cypher,
            params={
                "name": name,
                "domain": domain,
                "new_uuid": new_uuid,
                "schema_version": schema_version,
                "chunk_id": chunk_id_str,
            },
            # Must match the Cypher's "RETURN ... AS node_uuid" alias —
            # age_client projects this as the literal SQL output column
            # name, it does not infer it from the Cypher text. See
            # age_client.py module docstring point 1.
            columns=("node_uuid",),
        )
        if not rows:
            # Should never happen (MERGE+RETURN always yields a row), but
            # fail loudly rather than silently dropping the link.
            raise RuntimeError(f"MERGE returned no row for entity ({label}, {name}, {domain})")

        returned_uuid = rows[0]["node_uuid"]
        return UUID(returned_uuid)

    # ------------------------------------------------------------------
    # Typed relationship MERGE (replaces old MENTIONED_WITH heuristic)
    # ------------------------------------------------------------------

    @staticmethod
    async def _merge_typed_relationships(
        tx: age_client.GraphTransaction,
        triples: list[triple_extractor.Triple],
        node_uuid_by_name: dict[str, UUID],
    ) -> None:
        """
        Write each validated typed triple as a directed edge labeled with
        its specific predicate (e.g. TREATED_BY, CAUSED_BY), MERGE'd on
        (subject node_uuid, predicate, object node_uuid) so re-running
        extraction on the same chunk doesn't duplicate edges.

        triple_extractor.extract_triples() has already validated that:
          - subject/object are real NER entities from this chunk
          - predicate is in the domain's closed relationship_types set
          - subject/object NER labels match the predicate's declared from/to

        node_uuid_by_name resolves triple subject/object text back to the
        node_uuid minted in _merge_entity_node above for this same chunk —
        a lookup miss here would mean a triple referenced an entity text
        that didn't get MERGE'd, which should be impossible given
        triple_extractor's validation, but is checked defensively rather
        than risking a partial/garbage edge.
        """
        for triple in triples:
            subject_uuid = node_uuid_by_name.get(triple.subject)
            object_uuid = node_uuid_by_name.get(triple.object)

            if subject_uuid is None or object_uuid is None:
                logger.warning(
                    "Skipping triple (%s -[%s]-> %s): could not resolve to a node_uuid "
                    "from this chunk's entities — should be unreachable, flagging for review.",
                    triple.subject, triple.predicate, triple.object,
                )
                continue

            # Predicate is validated against a closed allow-list in
            # triple_extractor.py (alphanumeric ontology relationship
            # names only), so it's safe to interpolate into the edge
            # label here the same way entity labels already are above.
            cypher = f"""
            MATCH (a {{node_uuid: $subject_uuid}}), (b {{node_uuid: $object_uuid}})
            MERGE (a)-[:{triple.predicate}]->(b)
            """
            await tx.run(
                cypher,
                params={
                    "subject_uuid": str(subject_uuid),
                    "object_uuid": str(object_uuid),
                },
            )

    # ------------------------------------------------------------------
    # Reverse link: Chunk.graph_node_ids (Postgres, sync)
    # ------------------------------------------------------------------

    @staticmethod
    def _write_chunk_graph_links(chunk_node_links: dict[UUID, list[UUID]]) -> None:
        """
        One UPDATE per chunk that actually had entities extracted. Chunks
        with zero entities are skipped (graph_node_ids stays NULL/empty),
        which is the correct, honest state — not every chunk mentions a
        named entity from the domain ontology.
        """
        with SessionLocal() as db:
            from sqlalchemy import update
            for chunk_id, node_uuids in chunk_node_links.items():
                if not node_uuids:
                    continue
                # De-dupe in case the same node was MERGE'd twice within
                # one chunk (e.g. the same drug name mentioned twice).
                deduped = list(dict.fromkeys(node_uuids))
                db.execute(
                    update(ChunkModel)
                    .where(ChunkModel.id == chunk_id)
                    .values(graph_node_ids=deduped)
                )
            db.commit()