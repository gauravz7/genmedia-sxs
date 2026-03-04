# Project Pulse

Project Pulse is an internal GenMedia benchmarking and side-by-side (SxS) evaluation platform. It is designed to orchestrate complex multi-model prompting pipelines (T2V, I2V, R2V) and gather human-in-the-loop rankings.

## Architecture
- **Frontend:** Next.js application (React, Tailwind, Turbopack) interfacing with custom REST APIs.
- **Backend:** Python FastAPI backend orchestrating `google-genai`, `fal-client`, and Vertex AI endpoints.
- **Storage:** Google Cloud Storage (GCS) and Firestore.

## Getting Started
1. Install backend requirements and start Uvicorn (`./restart_local.sh`).
2. Boot the Next.js development server (`cd frontend && npm run dev`).
3. View the admin control plane at `http://localhost:3000/admin`.
4. Perform SxS rating at `http://localhost:3000/`.

## Deployment
Automated unified deployment is configured for Google Cloud Run via `./deploy_unified.sh`. The system runs via Docker container targeting regions such as `us-central1`.

For evaluation testing guidelines, refer to `docs/EVALUATOR_GUIDELINES.md`.
