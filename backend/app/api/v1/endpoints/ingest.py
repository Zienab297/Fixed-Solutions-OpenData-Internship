"""
/ingest endpoint — handles document, structured data, and web ingestion.
All processing is async via Celery workers.
"""
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from uuid import UUID, uuid4

from app.core.database import get_db
from app.api.v1.dependencies.auth import get_current_user, require_domain_access
from app.models.schemas.auth import CurrentUser
from app.models.schemas.ingest import WebIngestRequest, IngestJobResponse
from app.workers.tasks import process_document, process_web_crawl

router = APIRouter(prefix="/ingest", tags=["Ingestion"])


@router.post("/document", response_model=IngestJobResponse)
async def ingest_document(
    domain_id: UUID = Form(...),
    title: str = Form(None),
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a document (PDF, DOCX, CSV, XLSX) for async ingestion.
    Returns a job ID immediately — processing happens in background.
    """
    # RBAC: contributor or above required
    await require_domain_access(domain_id, "contributor", current_user, db)

    # Validate file type
    allowed_types = ["application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                     "text/csv", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"]
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file.content_type}")

    # Save file temporarily and create document record
    file_content = await file.read()
    document_id = uuid4()

    await db.execute(
        text("""
            INSERT INTO rag.documents (id, domain_id, title, source_type, ingest_status, ingested_by)
            VALUES (:id, :domain_id, :title, :source_type, 'pending', 
                    (SELECT id FROM rag.users WHERE keycloak_id = :user_id))
        """),
        {
            "id": str(document_id),
            "domain_id": str(domain_id),
            "title": title or file.filename,
            "source_type": "pdf" if "pdf" in file.content_type else "docx",
            "user_id": current_user.id,
        },
    )

    # Dispatch async Celery task
    job = process_document.delay(
        document_id=str(document_id),
        domain_id=str(domain_id),
        file_content=file_content,
        filename=file.filename,
    )

    return IngestJobResponse(
        job_id=job.id,
        document_id=document_id,
        status="pending",
        message="Document queued for processing. Poll /ingest/status/{job_id} for updates.",
    )


@router.post("/web", response_model=IngestJobResponse)
async def ingest_web(
    request: WebIngestRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger web crawl for a domain. URLs validated against domain whitelist."""
    await require_domain_access(request.domain_id, "contributor", current_user, db)

    # Validate URLs against domain whitelist
    result = await db.execute(
        text("SELECT url_whitelist FROM rag.crawl_configs WHERE domain_id = :domain_id"),
        {"domain_id": str(request.domain_id)},
    )
    config = result.fetchone()
    if not config:
        raise HTTPException(status_code=404, detail="No crawl configuration found for this domain")

    # Check all seed URLs are whitelisted
    whitelist = config.url_whitelist
    for url in request.seed_urls:
        if not any(str(url).startswith(w) for w in whitelist):
            raise HTTPException(
                status_code=400,
                detail=f"URL {url} is not in the domain whitelist. Update crawl config first.",
            )

    job = process_web_crawl.delay(
        domain_id=str(request.domain_id),
        seed_urls=[str(u) for u in request.seed_urls],
        max_depth=request.max_depth,
    )

    return IngestJobResponse(
        job_id=job.id,
        status="pending",
        message="Web crawl queued. Processing in background.",
    )


@router.get("/status/{job_id}")
async def get_ingest_status(job_id: str):
    """Poll ingestion job status."""
    from app.workers.celery_app import celery_app
    result = celery_app.AsyncResult(job_id)
    return {"job_id": job_id, "status": result.status, "result": result.result}
