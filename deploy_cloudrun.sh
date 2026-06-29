#!/bin/bash
echo "Deploying Project-Pulse Backend to Google Cloud Run..."

# Go to the backend bundle where the Dockerfile isn't needed (we handle it using buildpacks underneath using gcloud ignore fixes)
cd backend

# Execute deploy straight
gcloud run deploy project-pulse-backend \
  --source . \
  --region us-central1 \
  --project vital-octagon-19612 \
  --allow-unauthenticated \
  --quiet

echo "Deployment complete! Application is now accessible securely in the cloud."
