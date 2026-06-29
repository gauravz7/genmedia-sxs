#!/bin/bash
echo "Deploying Project-Pulse Unified Application (Frontend + Backend) to Google Cloud Run..."

# Go to the root project bundle where the unified Dockerfile lives
cd "$(dirname "$0")"

# Execute deploy straight
gcloud run deploy project-pulse-backend \
  --source . \
  --region us-central1 \
  --project vital-octagon-19612 \
  --allow-unauthenticated \
  --quiet

echo "Deployment complete! Application is now accessible securely in the cloud."
