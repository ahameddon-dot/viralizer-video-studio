FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app
COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /app/data/daily_trends /app/output/pdf

EXPOSE 8000
# Media rendering belongs on the dedicated Render background worker. Starting it
# inside the web container can starve the ASGI event loop and make Render's
# five-second health probe restart an otherwise healthy service.
#
# Keep two ASGI workers in the web container so a slow provider request cannot
# prevent /health from answering. WEB_CONCURRENCY remains configurable for
# larger instances, while two is safe for the current lightweight web process.
CMD if [ "${RUN_MEDIA_WORKER_IN_WEB:-false}" = "true" ]; then (while true; do python durable_media_worker.py; sleep 5; done) & fi; exec uvicorn app:app --host 0.0.0.0 --port ${PORT} --workers ${WEB_CONCURRENCY:-2}
