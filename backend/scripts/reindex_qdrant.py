"""Rebuild Qdrant collections from persisted Postgres chunks.

Run from the repository root:
    python backend/scripts/reindex_qdrant.py

Use --domain-id <uuid> to rebuild a single domain collection.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from sqlalchemy import select, update

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.db.models import Chunk, Document, Domain
from app.services.ingestion.embedder import EmbeddingService

logger = logging.getLogger(__name__)

COLLECTION_BATCH_SIZE = 100
EMBED_BATCH_SIZE = 32


def collection_name(domain_id: UUID) -> str:
    return f"domain_{str(domain_id).replace('-', '_')}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Drop and rebuild Qdrant domain collections from rag.chunks."
    )
    parser.add_argument(
        "--domain-id",
        type=UUID,
        help="Only rebuild the Qdrant collection for this domain.",
    )
    parser.add_argument(
        "--keep-existing",
        action="store_true",
        help="Do not delete existing collections before recreating/upserting.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List domains/chunk counts without changing Qdrant or Postgres.",
    )
    return parser.parse_args()


def ensure_collection(
    client: QdrantClient,
    name: str,
    *,
    keep_existing: bool,
) -> None:
    existing = {collection.name for collection in client.get_collections().collections}
    if name in existing and not keep_existing:
        client.delete_collection(collection_name=name)
        existing.remove(name)
        logger.info("Deleted existing Qdrant collection %s", name)

    if name not in existing:
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(
                size=settings.EMBEDDING_DIMENSION,
                distance=Distance.COSINE,
            ),
        )
        logger.info("Created Qdrant collection %s", name)


def list_domains(domain_id: UUID | None) -> list[Domain]:
    with SessionLocal() as db:
        query = select(Domain).join(Chunk, Chunk.domain_id == Domain.id).distinct()
        if domain_id is not None:
            query = query.where(Domain.id == domain_id)
        return list(db.execute(query).scalars().all())


def count_chunks(domain_id: UUID) -> int:
    with SessionLocal() as db:
        return len(
            db.execute(select(Chunk.id).where(Chunk.domain_id == domain_id))
            .scalars()
            .all()
        )


def reindex_domain(
    client: QdrantClient,
    embedder: EmbeddingService,
    domain: Domain,
    *,
    keep_existing: bool,
) -> int:
    name = collection_name(domain.id)
    ensure_collection(client, name, keep_existing=keep_existing)

    total = 0
    offset = 0

    with SessionLocal() as db:
        while True:
            rows = db.execute(
                select(Chunk, Document)
                .join(Document, Document.id == Chunk.document_id)
                .where(Chunk.domain_id == domain.id)
                .order_by(Document.title, Chunk.chunk_index)
                .offset(offset)
                .limit(EMBED_BATCH_SIZE)
            ).all()
            if not rows:
                break

            chunks = [row[0] for row in rows]
            documents = [row[1] for row in rows]
            vectors = embedder.embed_sync([chunk.content for chunk in chunks])
            points = [
                PointStruct(
                    id=str(chunk.id),
                    vector=vectors[index],
                    payload={
                        "content": chunk.content,
                        "document_title": documents[index].title,
                        "page_number": chunk.page_number,
                        "section": chunk.section,
                        "domain_id": str(domain.id),
                        "domain_name": domain.name,
                        "chunk_index": chunk.chunk_index,
                        "created_at": (
                            chunk.created_at.isoformat() if chunk.created_at else None
                        ),
                    },
                )
                for index, chunk in enumerate(chunks)
            ]

            for start in range(0, len(points), COLLECTION_BATCH_SIZE):
                client.upsert(
                    collection_name=name,
                    points=points[start : start + COLLECTION_BATCH_SIZE],
                )

            db.execute(
                update(Chunk)
                .where(Chunk.id.in_([chunk.id for chunk in chunks]))
                .values(embedding_model=settings.EMBEDDING_MODEL)
            )
            db.commit()

            total += len(rows)
            offset += len(rows)
            logger.info("Reindexed %d chunks for domain %s", total, domain.name)

    return total


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()

    domains = list_domains(args.domain_id)
    if not domains:
        logger.warning("No domains with chunks found to reindex.")
        return 0

    if args.dry_run:
        for domain in domains:
            logger.info(
                "Would rebuild %s (%s): %d chunks",
                domain.name,
                domain.id,
                count_chunks(domain.id),
            )
        return 0

    client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
    embedder = EmbeddingService()

    grand_total = 0
    for domain in domains:
        count = reindex_domain(
            client,
            embedder,
            domain,
            keep_existing=args.keep_existing,
        )
        logger.info(
            "Finished domain %s (%s): %d chunks",
            domain.name,
            domain.id,
            count,
        )
        grand_total += count

    logger.info("Reindex complete: %d total chunks", grand_total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
