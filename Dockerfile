# Python on GCP — Cloud Run (ECC deployment-patterns: multi-stage, non-root, pinned, HEALTHCHECK)
FROM python:3.11-slim AS builder
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml README.md ./
COPY src/ src/
RUN uv pip install --system --no-cache -e ".[gcp]" gunicorn || pip install --no-cache-dir -e ".[gcp]" gunicorn

FROM python:3.11-slim AS runner
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -r -u 1001 appuser

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY pyproject.toml README.md ./
COPY src/ src/
COPY evals/ evals/
COPY data/ data/

# SQLite demo DB at build; prod uses DATABASE_URL (Cloud SQL) — no secrets in image
RUN python -m src.provisioning.db || true
RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

CMD ["sh", "-c", "exec gunicorn --bind :$PORT --workers 1 --worker-class uvicorn.workers.UvicornWorker --timeout 0 src.main:app"]
