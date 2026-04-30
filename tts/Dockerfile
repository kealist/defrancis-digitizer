FROM python:3.10-slim
ENV PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir edge-tts==6.1.12
WORKDIR /app
COPY tts/tts.py /app/
CMD ["python", "/app/tts.py", "/output", "/audio"]
