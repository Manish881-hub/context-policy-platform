#!/usr/bin/env bash
set -euo pipefail
# Deploy to GCP Cloud Run — for Bhubaneswar on-site team, Python on GCP

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-asia-south1}"
IMAGE="gcr.io/$PROJECT_ID/context-policy-platform:$(git rev-parse --short HEAD)"

echo ">> Building $IMAGE"
gcloud builds submit --config cloudbuild.yaml --substitutions=_REGION="$REGION" .

echo ">> Deploying to Cloud Run ($REGION)"
gcloud run deploy context-policy-platform \
  --image "$IMAGE" \
  --region "$REGION" \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars PROVISIONING_DB_PATH=/app/src/provisioning/provisioning.db \
  --memory 512Mi --cpu 1 --port 8080 \
  --project "$PROJECT_ID"

echo ">> Health check"
URL=$(gcloud run services describe context-policy-platform --region "$REGION" --format 'value(status.url)' --project "$PROJECT_ID")
curl -s "$URL/health" | jq .

echo ">> Demo: on-site allow vs unauthorized deny"
curl -s -X POST "$URL/tool/wifi" -H "Content-Type: application/json" \
  -d '{"subscriber_id":"S123","technician_id":"T42","queue_origin":"field_app","gps_verified_on_site":true,"field_checkin_active":true,"site_id":"SITE_A","subscriber_site_id":"SITE_A"}' | jq .
curl -s -X POST "$URL/tool/wifi" -H "Content-Type: application/json" \
  -d '{"subscriber_id":"S123","technician_id":"T42","queue_origin":"support_unauthorized"}' | jq .
