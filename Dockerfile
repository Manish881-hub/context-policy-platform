# Python on GCP — Cloud Run
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps (for psycopg if you swap to Cloud SQL Postgres later)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src/ src/
COPY evals/ evals/
COPY data/ data/

RUN pip install --upgrade pip \
    && pip install -e ".[gcp]" \
    && pip install gunicorn

# Ensure DB exists at build (demo SQLite); prod mounts Cloud SQL via env PROVISIONING_DB_PATH
RUN python -m src.provisioning.db || true

EXPOSE 8080

# Cloud Run expects PORT env
CMD exec gunicorn --bind :$PORT --workers 1 --worker-class uvicorn.workers.UvicornWorker --timeout 0 src.main:app
