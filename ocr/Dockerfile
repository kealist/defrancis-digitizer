FROM python:3.10-slim

# Stream stdout/stderr immediately so docker compose logs show progress live
ENV PYTHONUNBUFFERED=1

# poppler-utils → pdftoppm (used by pdf2image)
# libgl1 + others → required by opencv, which PaddleOCR uses internally
RUN apt-get update && apt-get install -y --no-install-recommends \
        poppler-utils \
        libgomp1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
        libgl1 \
    && rm -rf /var/lib/apt/lists/*

# PaddleOCR 3.0.1 + PaddlePaddle 3.0.0 — last known-good combo as of writing.
# (3.1.x has a runtime API mismatch — see PaddleOCR issue #16287.)
RUN pip install --no-cache-dir \
        paddlepaddle==3.0.0 \
        paddleocr==3.0.1 \
        pdf2image==1.17.0 \
        Pillow==10.4.0

WORKDIR /app
# Build context is the project root, so the COPY paths are relative to that.
COPY ocr/preprocess.py ocr/ocr.py /app/
COPY reconstruct/reconstruct_layout.py reconstruct/find_sections.py /app/

CMD ["python", "ocr.py"]
