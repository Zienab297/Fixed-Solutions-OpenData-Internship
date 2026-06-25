FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements-docker.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Preload the Arabic OCR models into the image so runtime ingestion does not
# need to download PaddleOCR weights on first scanned-PDF upload.
RUN python -c "import numpy as np; from paddleocr import PaddleOCR; ocr = PaddleOCR(lang='ar', device='cpu'); ocr.predict(np.zeros((64, 256, 3), dtype=np.uint8))"

COPY backend/app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
