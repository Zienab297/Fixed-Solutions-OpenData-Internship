from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, UploadFile, File

from app.core.config import settings

router = APIRouter(tags=["PDF Processing"])


@router.post("/upload-pdf/")
async def upload_pdf(file: UploadFile = File(...)):
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)

    safe_name = Path(file.filename or "upload.pdf").name
    file_path = upload_dir / f"{uuid4()}-{safe_name}"
    file_path.write_bytes(await file.read())

    from app.services.ingestion.rag import process_pdf

    chunks = process_pdf(str(file_path))
    return {"message": "PDF processed successfully", "chunks": len(chunks)}
