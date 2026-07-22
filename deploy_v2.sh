#!/bin/bash
# Deploy the GenMedia SxS v2 build (video + IMAGE + TTS modalities) as its own
# Cloud Run service, separate from the original project-pulse-sxs. Unified image:
# FastAPI serves the static-exported Next.js build (root Dockerfile).
set -euo pipefail

PROJECT=vital-octagon-19612
REGION=us-central1
SERVICE=genmedia-sxs-v2
RUNTIME_SA=claude@vital-octagon-19612.iam.gserviceaccount.com

gcloud config set project "$PROJECT"

gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --service-account "$RUNTIME_SA" \
  --allow-unauthenticated \
  --memory 4Gi \
  --cpu 4 \
  --timeout 3600 \
  --concurrency 20 \
  --no-cpu-throttling \
  --min-instances 1 \
  --set-env-vars "GCP_PROJECT_ID=${PROJECT},GCS_BUCKET_NAME=project-pulse,OMNI_PROJECT=${PROJECT},EVAL_PROJECT=${PROJECT},EVAL_LOCATION=global,ADMIN_USER=admin" \
  --set-secrets "FAL_KEY=FAL_KEY:latest,ADMIN_PASS=ADMIN_PASS:latest,ELEVENLABS_API_KEY=ELEVENLABS_API_KEY:latest"

echo
echo "Deployed. URL:"
gcloud run services describe "$SERVICE" --region "$REGION" --format="value(status.url)"
