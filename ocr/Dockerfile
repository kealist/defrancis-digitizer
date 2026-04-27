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

# PaddleOCR 3.x with PaddlePaddle 3.x — the current stable stack.
# PP-OCRv5 (default model) recognizes Simplified Chinese, Traditional Chinese,
# Chinese Pinyin, English, and Japanese with a single multilingual model, so
# no `lang=` argument is needed.
RUN pip install --no-cache-dir \
        paddlepaddle==3.0.0 \
        paddleocr==3.0.1 \
        pdf2image==1.17.0 \
        Pillow==10.4.0

WORKDIR /app
COPY preprocess.py ocr.py /app/

CMD ["python", "ocr.py"]
