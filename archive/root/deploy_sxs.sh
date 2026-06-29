#!/bin/bash
# Deploy the SxS (Seedance vs Omni) branch as its own Cloud Run service,
# separate from the existing project-pulse-backend. Unified image: FastAPI
# serves the static-exported Next.js build (root Dockerfile).
set -euo pipefail

PROJECT=vital-octagon-19612
REGION=us-central1
SERVICE=project-pulse-sxs
RUNTIME_SA=claude@vital-octagon-19612.iam.gserviceaccount.com

gcloud config set project "$PROJECT"

gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --service-account "$RUNTIME_SA" \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --timeout 3600 \
  --concurrency 20 \
  --set-env-vars "GCP_PROJECT_ID=${PROJECT},GCS_BUCKET_NAME=project-pulse,OMNI_PROJECT=cloud-llm-preview1,EVAL_PROJECT=cloud-llm-preview1,EVAL_LOCATION=global,ADMIN_USER=admin" \
  --set-secrets "FAL_KEY=FAL_KEY:latest,ADMIN_PASS=ADMIN_PASS:latest"

echo
echo "Deployed. URL:"
gcloud run services describe "$SERVICE" --region "$REGION" --format="value(status.url)"
