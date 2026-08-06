#!/usr/bin/env bash
# Run the v3 backend locally on :8021 against REAL Firestore + providers.
# Reads v3/.env (provider keys, GCP project, admin) via pydantic-settings.
# GCP auth uses Application Default Credentials (gcloud auth application-default login).
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-8021}"

# Kill any existing uvicorn on this port.
pkill -f "uvicorn app.main:app.*--port ${PORT}" 2>/dev/null || true
sleep 1

echo "Starting v3 backend on http://localhost:${PORT} (real Firestore + providers)"
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT}" --reload
