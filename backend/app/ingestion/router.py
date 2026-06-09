from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.v1.dependencies.auth import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.ingestion.models import IngestionJob
from app.ingestion.schemas import IngestStatus
from app.ingestion.tasks import process_pdf
from app.models.user import User


router = APIRouter(prefix="/ingest", tags=["ingestion"])


@router.post("", response_model=IngestStatus, status_code=status.HTTP_202_ACCEPTED)
async def ingest_pdf(
    domain_id: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> IngestionJob:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF uploads are supported.",
        )

    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)

    safe_name = Path(file.filename).name
    stored_name = f"{uuid4()}-{safe_name}"
    file_path = upload_dir / stored_name
    content = await file.read()
    file_path.write_bytes(content)

    job = IngestionJob(
        domain_id=domain_id,
        filename=safe_name,
        file_path=str(file_path),
        status="pending",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    process_pdf.delay(job.id)
    return job


@router.get("/{job_id}", response_model=IngestStatus)
def get_ingestion_status(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> IngestionJob:
    job = db.query(IngestionJob).filter(IngestionJob.id == job_id).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ingestion job not found.",
        )
    return job
