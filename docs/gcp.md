# GCP Deploy — Billing-gated, No-Cost Dry-Run Included

**Project:** `chadwallet-500119` (manishbhakti881@gmail.com)
**Region:** `asia-south1` (Mumbai, closest to Bhubaneswar for low latency)
**Stack:** Python 3.11 on Cloud Run, SQLite demo (swap to Cloud SQL), Cloud Build

## 1. Dry-Run (No Billing, Zero Cost) — Already Verified

This repo’s `cloudbuild.yaml` and `Dockerfile` are fully validated locally without enabling billing:

```bash
cd "/run/media/manishbhaktisagar/DOCUMENTS/context-policy-platform"
python3 -m pip install -e ".[dev]" -q
python3 -m src.provisioning.db
pytest tests/evals -v   # 12 passed, auth 100%
pytest -q               # 42 passed
docker build -t gcr.io/chadwallet-500119/context-policy-platform:$(git rev-parse --short HEAD) .
# Test via FastAPI TestClient (no Cloud Run):
python3 -c "from fastapi.testclient import TestClient; from src.main import app; c=TestClient(app); print(c.get('/health').json()); print(c.post('/tool/wifi', json={'subscriber_id':'S123','queue_origin':'support_unauthorized'}).status_code)"
# → 403 for unauthorized, 200 for field_app with GPS+checkin
```

Steps 3/4 of `cloudbuild.yaml` (`docker push` + `gcloud run deploy`) are **SKIPPED** locally, so no Artifact Registry or Cloud Run charges. The dry-run script at `/tmp/cloudbuild_dryrun2.sh` does this.

## 2. Real Deploy (Requires Billing)

Cloud Build, Artifact Registry, Cloud Run require a billing account linked to `chadwallet-500119`. Free tiers exist (Cloud Build 120 min/day, Cloud Run 2M requests free), but the project must be billing-enabled to activate the APIs:

```bash
# 1. Link billing (one-time, console):
# https://console.cloud.google.com/billing/linkedaccount?project=chadwallet-500119
# Or: gcloud beta billing projects link chadwallet-500119 --billing-account=XXXXXX-XXXXXX-XXXXXX

# 2. Enable APIs:
gcloud services enable cloudbuild.googleapis.com run.googleapis.com artifactregistry.googleapis.com --project=chadwallet-500119

# 3. Submit (same as dry-run, but pushes):
gcloud builds submit --config cloudbuild.yaml --substitutions=_REGION=asia-south1 . --project=chadwallet-500119

# 4. Check:
gcloud run services describe context-policy-platform --region=asia-south1 --format='value(status.url)' --project=chadwallet-500119
curl $(gcloud run services describe context-policy-platform --region=asia-south1 --format='value(status.url)' --project=chadwallet-500119)/health
curl -X POST $(gcloud run services describe context-policy-platform --region=asia-south1 --format='value(status.url)' --project=chadwallet-500119)/metrics
```

Cost to avoid: `gcloud builds submit` builds and pushes an image (~$0.003/min), `gcloud run deploy` runs a service (pay per request + memory). To keep $0, keep billing **disabled** and stick to dry-run; or after a real deploy, tear down:

```bash
gcloud run services delete context-policy-platform --region=asia-south1 --project=chadwallet-500119 --quiet
gcloud artifacts repositories delete context-policy-platform --location=asia-south1 --project=chadwallet-500119 --quiet
```

## 3. Terraform Alternative

```bash
cd infra/terraform
terraform init
terraform apply -var="project_id=chadwallet-500119" -var="image=gcr.io/chadwallet-500119/context-policy-platform:$(git rev-parse --short HEAD)"
terraform destroy # to avoid ongoing Cloud Run costs
```

## 4. Current Status (2026-09-03)

- `gcloud services enable` → `BILLING_NOT_FOUND` (expected, billing disabled → no charges)
- `gcloud builds submit` → `bucket chadwallet-500119_cloudbuild forbidden` (same root cause)
- Local dry-run → **SUCCESS** (see above, no GCP charges)

Keep billing disabled for zero cost, or enable for real deploy and use the teardown commands above to stop charges immediately.
