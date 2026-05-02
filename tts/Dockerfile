FROM python:3.10-slim
ENV PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y ffmpeg && apt-get clean && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir edge-tts pydub
WORKDIR /app
COPY tts/tts.py /app/
CMD ["python", "/app/tts.py", "/output", "/audio"]
