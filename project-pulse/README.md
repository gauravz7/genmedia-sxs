# GenMedia SxS

**Internal benchmarking platform for side-by-side (SxS) evaluation of generative media models.**

Compare Veo, Kling, Seedance and other AI video models through blind pairwise testing with structured human ratings.

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  Cloud Run                       │
│  ┌──────────────┐      ┌──────────────────────┐ │
│  │  Next.js      │      │  FastAPI Backend     │ │
│  │  (static)     │─────▶│  uvicorn :8080       │ │
│  │  React 19     │      │                      │ │
│  │  Tailwind CSS │      │  /api/*  endpoints   │ │
│  └──────────────┘      └────────┬─────────────┘ │
└─────────────────────────────────┼───────────────┘
                                  │
          ┌───────────────────────┼───────────────────────┐
          │                       │                       │
  ┌───────▼───────┐   ┌──────────▼────────┐   ┌─────────▼────────┐
  │  Firestore     │   │  Cloud Storage     │   │  Model APIs       │
  │  (jobs, votes, │   │  (videos, images)  │   │  • Vertex AI (Veo)│
  │   prompts)     │   │                    │   │  • FAL (Kling,    │
  └───────────────┘   └───────────────────┘   │    Seedance)      │
                                               └──────────────────┘
```

- **Frontend:** Next.js 16 / React 19 / Tailwind CSS — static export served by FastAPI
- **Backend:** Python FastAPI orchestrating Vertex AI, FAL, Firestore, and GCS
- **Database:** Google Firestore (collections: `eval_jobs`, `prompts`, `votes`)
- **Storage:** Google Cloud Storage
- **Deployment:** Unified Docker container on Google Cloud Run

## Features

- **Blind SxS Evaluation** — Randomized left/right video pairing with 6-metric rating (Motion Quality, Prompt Following, Aesthetic, Audio Expressiveness, Audio-Visual Sync, Audio Prompt Following)
- **Multi-Model Generation** — Text-to-Video (T2V), Image-to-Video (I2V), Reference-to-Video (R2V) across Veo, Kling, Seedance
- **Admin Console** — Prompt management, model registry, batch CSV/Google Sheets import, auto-tagging via Gemini
- **Leaderboard & Analytics** — Real-time win rates, per-category breakdowns, voter leaderboard
- **10-Vote Gate** — Users must complete 10 evaluations before unlocking prompt submission

## Getting Started

### Prerequisites

- Python 3.12+
- Node.js 20+
- GCP project with Firestore, Cloud Storage, and Vertex AI enabled
- FAL API key (for Kling/Seedance)

### Local Development

```bash
# 1. Clone and navigate
git clone https://github.com/gauravz7/genmedia-sxs.git
cd genmedia-sxs/project-pulse

# 2. Backend setup
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 3. Create backend/.env (never commit this file)
cat > .env << 'EOF'
GCP_PROJECT_ID=your-gcp-project
GCS_BUCKET_NAME=your-bucket
FAL_KEY=your-fal-api-key
OUTPUT_GCS_BUCKET=gs://your-bucket
ADMIN_USER=admin
ADMIN_PASS=your-admin-password
EOF

# 4. Start backend
uvicorn main:app --reload --port 8011

# 5. Frontend (new terminal)
cd ../frontend
npm ci
npm run dev
```

The frontend proxies API calls to the backend via Next.js rewrites (`/proxy-api/` → `localhost:8011`).

- Admin console: `http://localhost:3000/admin`
- SxS evaluation: `http://localhost:3000/`
- API docs: `http://localhost:8011/docs`

## Deployment

Unified deployment to Cloud Run (builds frontend + backend in a single container):

```bash
./deploy_unified.sh
```

This runs `gcloud run deploy` with the multi-stage `Dockerfile` that:
1. Builds the Next.js static export (`npm run build`)
2. Packages it with the FastAPI backend
3. Serves everything via uvicorn on port 8080

Set secrets as Cloud Run env vars (not in code):
```bash
gcloud run services update genmedia-sxs \
  --set-env-vars "FAL_KEY=...,ADMIN_PASS=..." \
  --region us-central1
```

## Input Format (Video SxS — Seedance 2.0 vs Gemini Omni)

Upload a **JSON array** of cases (or `{"cases": [ … ]}`) via `/sxs` (GCS path or file
upload) or admin **Generate (JSON)** → `POST /api/admin/generate-json`. A case is keyed by
**`customer` + `id`**; already-completed cases are skipped on re-run (dedup).

| Field | Required | Notes |
|-------|----------|-------|
| `prompt` | **yes** | generation prompt |
| `modality` | **yes** | `T2V`, `I2V`, `R2V` (also `V2V`, `FLF2V (...)`, `Ref2V`). FLF2V / first-frame → **i2v**; V2V / Ref2V → **r2v** |
| `id` | recommended | case id (dedup key with `customer`) |
| `customer` | optional | grouping key |
| `reference_images` | conditional | `gs://`/`https://` URLs. Required for **I2V** (first frame; 2nd = last frame for FLF2V) and **R2V** |
| `reference_videos` | conditional | for **V2V** (source video) / R2V |
| `aspect_ratio` | optional | `16:9` (default) or `9:16` |
| `duration` | optional | integer seconds 4–15 (default 8) |

```json
{
  "customer": "opus", "id": "V-1", "modality": "I2V",
  "prompt": "A green frog hops right onto a second lily pad, then a third.",
  "reference_images": ["gs://project-pulse/sxs/opus/inputs/ref1.png"],
  "reference_videos": [], "aspect_ratio": "16:9", "duration": 8
}
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/models` | GET | List registered models |
| `/api/models` | POST | Add a new model |
| `/api/generate` | POST | Trigger async video generation |
| `/api/evaluation/pair` | GET | Get random SxS pair for rating |
| `/api/evaluation/vote` | POST | Submit evaluation vote |
| `/api/evaluation/stats` | GET | Win rates and leaderboard |
| `/api/admin/prompts` | GET/POST | Manage prompts |
| `/api/admin/batch/sheet/load` | POST | Import batch from Google Sheet |
| `/api/admin/generate-tags` | POST | Auto-tag prompts with Gemini |
| `/api/leaderboard/users` | GET | Voter leaderboard |
| `/api/health` | GET | Health check |

## Project Structure

```
project-pulse/
├── Dockerfile              # Multi-stage unified build
├── deploy_unified.sh       # Cloud Run deployment script
├── backend/
│   ├── main.py             # FastAPI application
│   ├── requirements.txt    # Python dependencies
│   ├── providers/
│   │   ├── fal_provider.py     # FAL API (Kling, Seedance)
│   │   └── vertex_provider.py  # Vertex AI (Veo, Gemini)
│   └── util/
│       ├── gcs_utils.py        # GCS storage operations
│       └── sheets_utils.py     # Google Sheets integration
├── frontend/
│   ├── src/app/
│   │   ├── page.tsx            # SxS evaluation UI
│   │   └── admin/page.tsx      # Admin console
│   ├── package.json
│   └── next.config.ts
└── docs/
    ├── EVALUATOR_GUIDELINES.md
    └── README_BATCH.md
```

## Documentation

- [Evaluator Guidelines](docs/EVALUATOR_GUIDELINES.md) — Rating rubric and evaluation criteria
- [Batch Evaluation Guide](docs/README_BATCH.md) — CSV/Sheets batch import workflow
