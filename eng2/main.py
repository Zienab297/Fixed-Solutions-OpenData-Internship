from fastapi import FastAPI, UploadFile, File
from rag import process_pdf

app = FastAPI()

@app.post("/upload-pdf/")
async def upload_pdf(file: UploadFile = File(...)):
    file_path = f"temp_{file.filename}"

    with open(file_path, "wb") as f:
        f.write(await file.read())

    process_pdf(file_path)

    return {"message": "PDF processed successfully"}