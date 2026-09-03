#!/usr/bin/env bash
set -euo pipefail
# Local Cloud Run simulation
pip install -e ".[gcp]"
python -m src.provisioning.db
uvicorn src.main:app --reload --port 8080 &
PID=$!
sleep 2
echo ">> /health"
curl -s http://localhost:8080/health | jq .
echo ">> /tool/wifi allow"
curl -s -X POST http://localhost:8080/tool/wifi -H "Content-Type: application/json" -d '{"subscriber_id":"S123","technician_id":"T42","queue_origin":"field_app","gps_verified_on_site":true,"field_checkin_active":true,"site_id":"SITE_A","subscriber_site_id":"SITE_A"}' | jq .
echo ">> /tool/wifi deny"
curl -s -X POST http://localhost:8080/tool/wifi -H "Content-Type: application/json" -d '{"subscriber_id":"S123","queue_origin":"support_unauthorized"}' | jq .
kill $PID
