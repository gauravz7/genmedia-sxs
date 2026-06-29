# Project Pulse Backend

Internal benchmarking platform for side-by-side (SxS) evaluation of generative video models. Compare Veo, Kling, Seedance, Grok, and other AI video models through blind pairwise testing with structured human ratings.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Key Components](#key-components)
- [API Reference](#api-reference)
  - [Health](#health)
  - [Video Generation](#video-generation)
  - [Image Operations](#image-operations)
  - [Model Registry](#model-registry)
  - [Prompt Management](#prompt-management)
  - [Tags & Categories](#tags--categories)
  - [Admin Job Management](#admin-job-management)
  - [Evaluation & Voting](#evaluation--voting)
  - [Statistics & Leaderboard](#statistics--leaderboard)
  - [Google Sheets Integration](#google-sheets-integration)
  - [Google Slides Generation](#google-slides-generation)
  - [Slideware (HTML Presentation)](#slideware-html-presentation)
  - [Media Proxy](#media-proxy)
  - [Authentication](#authentication)
- [Providers](#providers)
  - [Vertex AI / Veo](#vertex-ai--veo)
  - [FAL (Kling, Seedance, Grok)](#fal-kling-seedance-grok)
- [Utility Modules](#utility-modules)
  - [GCS Utils](#gcs-utils)
  - [Drive Utils](#drive-utils)
  - [Sheets Utils](#sheets-utils)
- [Standalone Scripts](#standalone-scripts)
- [Data Model](#data-model)
  - [Firestore Collections](#firestore-collections)
  - [Cloud Storage Layout](#cloud-storage-layout)
- [Model Registry (models.json)](#model-registry-modelsjson)
- [Environment Variables](#environment-variables)
- [Local Development](#local-development)
- [Deployment](#deployment)
  - [Docker](#docker)
  - [Cloud Run](#cloud-run)
- [Service Account Permissions](#service-account-permissions)
- [Troubleshooting](#troubleshooting)

---

## Architecture Overview

```
                        ┌──────────────────────────────────────────────────┐
                        │                   Cloud Run                      │
                        │                                                  │
                        │  ┌──────────────┐       ┌─────────────────────┐  │
                        │  │  Next.js      │       │  FastAPI Backend    │  │
User ──────────────────▶│  │  (static)     │──────▶│  uvicorn :8080     │  │
                        │  │  React 19     │       │                    │  │
                        │  │  Tailwind CSS │       │  /api/* endpoints  │  │
                        │  └──────────────┘       └────────┬───────────┘  │
                        └──────────────────────────────────┼──────────────┘
                                                           │
                ┌──────────────────────────────────────────┼──────────────────────┐
                │                  │                        │                      │
        ┌───────▼───────┐  ┌──────▼────────┐  ┌───────────▼──────────┐  ┌────────▼───────┐
        │  Firestore     │  │ Cloud Storage  │  │  Model APIs          │  │  Google Drive   │
        │  eval_jobs     │  │ gs://project-  │  │  - Vertex AI (Veo)   │  │  Shared Drive   │
        │  votes         │  │    pulse       │  │  - FAL (Kling,       │  │  video uploads   │
        │  prompts       │  │  videos/images │  │    Seedance, Grok)   │  │  + Slides gen    │
        │  slideware_    │  │               │  │  - Gemini (tagging)  │  │                 │
        │    feedback     │  │               │  │                     │  │                 │
        └───────────────┘  └───────────────┘  └─────────────────────┘  └─────────────────┘
```

**Stack:** Python 3.12 / FastAPI / Uvicorn / Google Cloud (Firestore, GCS, Vertex AI, Drive, Sheets, Slides)

---

## Key Components

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app — all API endpoints, background job orchestration, data managers |
| `providers/vertex_provider.py` | Google Vertex AI / Veo video generation + Gemini tagging |
| `providers/fal_provider.py` | FAL.ai provider — Kling, Seedance, Grok video generation |
| `util/gcs_utils.py` | GCS upload/download, signed URL generation, URL normalization |
| `util/drive_utils.py` | Google Drive video uploads to Shared Drive |
| `util/sheets_utils.py` | Google Sheets read/write for batch processing |
| `generate_google_slides.py` | Google Slides presentation generator (Pro/Fast tier layout) |
| `generate_pptx.py` | PowerPoint export with embedded videos |
| `generate_slideware.py` | Standalone HTML slideware presentation generator |
| `bulk_drive_upload.py` | Parallel bulk upload of GCS videos to Google Drive |
| `models.json` | Model registry — 50+ model definitions |

---

## API Reference

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Returns `{ status: "healthy", service: "Project Pulse Backend" }` |

---

### Video Generation

#### `POST /api/generate`

Queues video generation across selected models. Returns immediately; generation runs in background.

**Request body (PromptRequest):**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `text` | string | yes | Video generation prompt |
| `categories` | string[] | no | Tags (auto-generated via Gemini if omitted) |
| `ratio` | string | no | `"16:9"` or `"9:16"` (default: `"16:9"`) |
| `prompt_id` | string | no | Batch ID — reuses existing job if matched |
| `start_image_url` | string | no | First-frame image (triggers I2V mode) |
| `end_image_url` | string | no | Last-frame image |
| `reference_image_url` | string | no | Style reference image |
| `reference_images` | string[] | no | Multiple reference images (triggers R2V mode) |
| `model_ids` | string[] | no | Specific models to run; defaults to all active models for inferred mode |
| `mode` | string | no | `"t2v"`, `"i2v"`, or `"r2v"` — auto-inferred from images if omitted |

**Response:**
```json
{
  "job_id": "job_1682345678901",
  "prompt": "A golden sunset over mountains",
  "status": "queued",
  "initiation_time": 1682345678.5
}
```

**Background logic:**
- Mode inference: R2V if `reference_images` present, I2V if `start_image_url` present, else T2V
- If `prompt_id` matches an existing job, appends missing models (doesn't duplicate)
- Runs all model generations concurrently via `asyncio.gather()`
- Per-model failures don't abort the batch
- Previous successful results archived to `generation_history` before overwrite
- Auto-regenerates slideware HTML after completion

---

### Image Operations

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/upload` | Upload file via multipart form. Returns GCS URL + signed proxy URL |
| POST | `/api/generate-image` | Generate image via FAL Flux Schnell. Body: `{ prompt, ratio }`. Returns signed URL |

---

### Model Registry

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/models` | List all registered models (active + inactive) |
| POST | `/api/models` | Add new model. Body: `RegisteredModel` (id, name, provider, model_id, type, is_active) |
| POST | `/api/models/{model_id}/toggle` | Toggle `is_active` flag |
| DELETE | `/api/models/{model_id}` | Remove model from registry |

**RegisteredModel fields:**

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier (e.g., `"veo-3-1-001-t2v"`) |
| `name` | string | Display name (e.g., `"Veo 3.1 (T2V)"`) |
| `provider` | string | `"fal"` or `"vertex"` |
| `model_id` | string | Provider-specific model ID |
| `type` | string | `"t2v"`, `"i2v"`, or `"r2v"` |
| `is_active` | bool | Whether model is available for generation |

---

### Prompt Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/admin/prompts` | List all prompts ordered by timestamp |
| POST | `/api/admin/prompts` | Create prompt (auto-tags via Gemini if no categories provided) |
| DELETE | `/api/admin/prompts/{prompt_id}` | Delete prompt |

---

### Tags & Categories

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/tags` | Union of all unique tags from jobs and prompts |
| POST | `/api/admin/generate-tags` | Generate 3 tags via Gemini 2.5 Flash. Body: `{ text, start_image_url, end_image_url, reference_images }` |
| POST | `/api/admin/backfill-tags` | Auto-tag all jobs/prompts missing categories. Returns counts |

**Predefined categories (30):** Transport, Animation, Outdoor, Lighting, Water, Physics, Camera, Text rendering, Nature, Tech, Fantasy, Abstract, Buildings, Indoor, People, Prompt Length, Sports, Weather, Action, Food, Animals, Multi-scene, Fashion, Anime, Photorealistic, Screens, Era/Location, Sci-Fi — each emoji-coded.

---

### Admin Job Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/admin/jobs` | All jobs with signed URLs for images/videos/history |
| DELETE | `/api/admin/jobs/{job_id}` | Delete job and invalidate cache |
| POST | `/api/admin/jobs/{job_id}/retry` | Retry failed models. Query: `?include_stuck=true` to also retry "generating" status |
| GET | `/api/admin/jobs/{job_id}/status` | Real-time per-model status (fresh Firestore read, not cached) |

**Retry response:**
```json
{
  "retrying_models": ["seedance-2-0-t2v", "kling-3-pro-t2v"],
  "skipped_models": ["removed-model-id"]
}
```

**Status response:**
```json
{
  "total_models": 6,
  "succeeded": 4,
  "failed": 1,
  "errors": [{ "model": "kling-3-pro-t2v", "error": "Timeout" }],
  "all_done": false
}
```

---

### Evaluation & Voting

#### `GET /api/evaluation/pair`

Fetch a random video pair for blind evaluation.

**Query params:**

| Param | Type | Description |
|-------|------|-------------|
| `prompt_id` | string | Filter to specific batch |
| `tag` | string | Filter by category |
| `search` | string | Free-text prompt search |
| `veo_anchored` | bool | Ensure one side is always Veo |

**Response:**
```json
{
  "job_id": "prompt_uuid",
  "prompt": "A cat dancing in the rain",
  "categories": ["Animals", "Weather"],
  "ratio": "16:9",
  "start_image_url": "/api/media?url=gs%3A%2F%2F...",
  "variant_a": { "model_id": "veo-3-1-001-t2v", "url": "/api/media?url=..." },
  "variant_b": { "model_id": "seedance-2-0-t2v", "url": "/api/media?url=..." }
}
```

**Logic:**
- Groups jobs by `prompt_id`
- Includes current results AND previous versions from `generation_history`
- Validates URL accessibility (returns 404 if videos inaccessible)
- Randomly shuffles and pairs candidates
- Veo-anchored mode: only pairs with at least 1 Veo + 1 non-Veo model

#### `POST /api/evaluation/vote`

Record an evaluation.

**Request body (VoteRequest):**
```json
{
  "job_id": "prompt_id",
  "winner_side": "a",
  "winner_model": "veo-3-1-001-t2v",
  "loser_model": "seedance-2-0-t2v",
  "scores": {
    "motion": 7,
    "prompt": 8,
    "aesthetic": 6,
    "expressiveness": 9,
    "sync": 7
  },
  "justification": "Better motion quality and prompt adherence",
  "ldap": "john.doe"
}
```

**Score dimensions (1-10 scale):**
- `motion` — Motion Quality
- `prompt` — Prompt Following
- `aesthetic` — Aesthetic Consistency
- `expressiveness` — Audio Expressiveness
- `sync` — Audio-Visual Sync

#### `POST /api/admin/votes/prune`

Delete old votes. Query: `?keep=20` (default). Batches deletes in 500-doc chunks.

---

### Statistics & Leaderboard

#### `GET /api/evaluation/stats`

**Query params:** `ldap` (optional), `tag` (optional)

**Response:**
```json
{
  "global": {
    "total_evals": 150,
    "modes": { "T2V": 100, "I2V": 40, "R2V": 10 },
    "skus": [
      {
        "model_id": "veo-3-1-001-t2v",
        "win_rate": 65.5,
        "wins": 100,
        "total": 152,
        "latency_ps": 2.15,
        "t2v_rate": 70.0, "t2v_wins": 70, "t2v_total": 100,
        "t2v_scores": { "motion": 7.2, "prompt": 8.1 },
        "i2v_rate": 45.0, "i2v_wins": 18, "i2v_total": 40,
        "r2v_rate": 60.0, "r2v_wins": 6, "r2v_total": 10
      }
    ]
  },
  "user": { ... }
}
```

Computed metrics: win rates (global + per-mode), per-dimension averages (skips default "5"), average latency per model.

#### `GET /api/leaderboard/users`

Top 10 evaluators by vote count. Returns `{ leaderboard: [{ ldap, count }] }`.

---

### Google Sheets Integration

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/admin/batch/sheet/load` | Load Sheet by URL. Body: `{ url }`. Expected columns A-I (prompt data), J-K (status). Returns `{ rows }` |
| POST | `/api/admin/batch/sheet/update` | Update row status. Body: `{ url, row, success, error }`. Writes columns J (success) and K (error message) |

---

### Google Slides Generation

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/slides/generate` | Create/rebuild Slides presentation. Query: `?batches=X&force_new=false`. Returns `{ url }` |
| POST | `/api/slides/append/{batch_name}` | Append single batch to existing presentation |

**Slide layout per batch:**
1. **Input slide** — prompt text, categories/tags, input images (for I2V)
2. **Pro Tier slide** — Veo 3.1, Seedance 2.0, Kling 3 Pro side-by-side
3. **Fast Tier slide** — Veo Fast/Lite, Seedance Fast, Kling 2.x, Grok side-by-side

Presentation ID persisted in Firestore (`config/slides_presentation`).

---

### Slideware (HTML Presentation)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/slideware` | Serve generated `slideware.html` — dark Material Design theme with sidebar navigation |
| POST | `/api/slideware/regenerate` | Rebuild HTML slideware from all Firestore jobs |
| POST | `/api/slideware/pptx` | Generate PowerPoint with embedded videos. Query: `?batches=X`. Returns file download |
| GET | `/api/slideware/pptx/download` | Download most recent generated PPTX |
| GET | `/api/slideware/feedback` | Retrieve all slideware feedback |
| POST | `/api/slideware/feedback/pick` | Mark best video for batch+tier |
| POST | `/api/slideware/feedback/comment` | Add comment with timestamp |

---

### Media Proxy

#### `GET /api/media`

Proxies private GCS bucket access through the backend.

**Query:** `?url=gs%3A%2F%2Fbucket%2Fpath`

- Handles HTTP Range requests for video seeking
- Streams large files in 2MB chunks
- Supports `gs://`, path-style, and virtual-hosted GCS URLs
- Converts all URL formats to `gs://` internally

---

### Authentication

#### `POST /api/admin/login`

Simple hardcoded authentication for the admin console.

**Request:** `{ username: "admin", password: "password" }`

---

## Providers

### Vertex AI / Veo

**File:** `providers/vertex_provider.py`

**`generate_with_veo(prompt, ratio, image_url, model_id, reference_images, mode)`**

- Supports Veo 3.1 models (T2V, I2V, R2V)
- Preview models use `google-genai` SDK (`_generate_with_veo_sdk()`)
- Non-preview models use REST API with `PredictLongRunning`
- Polls for completion every 10 seconds (120 retries = 20-minute timeout)
- Retries on 503/high-load errors with 30-sec backoff (3 max attempts)
- Config: aspectRatio, durationSeconds=8, enhancePrompt=true, personGeneration="allow_adult", sampleCount=1, seed=777

**`generate_tags_with_gemini(prompt, start_image_url, end_image_url, reference_images)`**

- Calls Gemini 2.5 Flash with multimodal input (text + images)
- Returns exactly 3 tags from 30 predefined categories
- Fuzzy matching fallback for validation
- Default tags on error: `["Photorealistic", "People", "Indoor"]`

### FAL (Kling, Seedance, Grok)

**File:** `providers/fal_provider.py`

**`generate_with_fal(model_id, prompt, ratio, image_url, end_image_url, reference_images, mode)`**

- Subscribes to FAL models via `fal_client.subscribe_async()`
- Mode-specific parameters per model family:
  - **Kling v3/o3:** `aspect_ratio` or `ratio` depending on version, audio enabled for v3+
  - **Seedance 2.0:** `aspect_ratio`, `duration` as string, audio enabled for 2.0+
  - **Grok:** `aspect_ratio`, `duration=10`
- GCS URLs proxied through backend for FAL accessibility (`_ensure_accessible_to_fal`)
- Uploads output to GCS, returns GCS URL + latency

---

## Utility Modules

### GCS Utils

**File:** `util/gcs_utils.py`

| Function | Description |
|----------|-------------|
| `normalize_gcs_url(url)` | Strip query params from signed URLs |
| `https_to_gs(url)` | Convert `https://storage.googleapis.com/...` to `gs://...` |
| `get_upload_client()` | Singleton `storage.Client` (ADC-based) |
| `get_signed_url(gcs_url)` | Returns proxy URL: `/api/media?url=gs%3A%2F%2F...` |
| `upload_from_url(url, dest)` | Download from URL, upload to GCS bucket |
| `upload_from_path(path, dest)` | Upload local file to GCS |
| `upload_from_bytes(data, dest, content_type)` | Upload bytes to GCS |
| `download_blob_to_bytes(url)` | Download GCS blob to bytes |

### Drive Utils

**File:** `util/drive_utils.py`

| Function | Description |
|----------|-------------|
| `_get_drive_service()` | Singleton Drive API v3 client (ADC) |
| `_find_or_create_folder(name, parent_id)` | Create batch folder under parent (Shared Drive aware) |
| `upload_video_to_drive(video_url, filename, batch_name)` | Download video, upload to Drive with resumable chunked upload (10MB chunks) |

### Sheets Utils

**File:** `util/sheets_utils.py`

| Function | Description |
|----------|-------------|
| `get_sheets_token()` | Auth via `gcloud auth print-access-token` or ADC fallback |
| `read_sheet(sheet_id, range)` | Returns 2D array of cell values |
| `update_sheet_row(sheet_id, row, success, error)` | Update columns J and K |
| `get_sheet_id_from_url(url_or_id)` | Extract Sheet ID from sharing link |

---

## Standalone Scripts

### Slideware Generation

| Script | Description |
|--------|-------------|
| `generate_google_slides.py` | Create Google Slides with Pro/Fast tier layout. CLI: `--new` (rebuild), batch names (append specific), no args (append all missing) |
| `generate_pptx.py` | PowerPoint export with embedded GCS videos. Supports batch filtering |
| `generate_slideware.py` | Standalone HTML slideware — dark Material Design, sidebar nav, Pro/Fast tier comparison |

### Bulk Operations

| Script | Description |
|--------|-------------|
| `bulk_drive_upload.py` | Parallel bulk upload of all GCS videos to Google Drive. Args: `--dry-run`, `--workers N` (default 20). Thread-local Drive services to avoid httplib2 concurrency issues |

### Testing & Validation

| Script | Description |
|--------|-------------|
| `test_veo_sdk.py` | Test Veo SDK connectivity |
| `test_admin_seedance.py` | Test Seedance generation |
| `test_admin_jobs.py` | Test job management endpoints |
| `test_profile.py` | Profile backend performance |
| `test_speeds.py` | Measure model latencies |
| `test_upload_probe.py` | Test GCS upload pipeline |

### Database Maintenance

| Script | Description |
|--------|-------------|
| `show_db.py` | Display Firestore contents |
| `deep_scrub_firestore.py` | Remove all Firestore data (destructive) |
| `wipe_history.py` | Clear generation history |
| `delete_jobs.py` | Remove specific jobs |
| `fix_jobs.py` | Fix malformed job records |
| `scrub_firestore_urls.py` | Normalize URLs in Firestore |
| `inject_i2v_job.py` | Inject test I2V job |
| `migrate_to_firestore.py` | Migrate from old data store |

### Google Sheets Setup

| Script | Description |
|--------|-------------|
| `add_sheet_dropdown.py` | Add dropdown validation to Sheet columns |
| `check_columns.py` | Verify column schema |
| `create_test_sheet.py` | Create test spreadsheet |

---

## Data Model

### Firestore Collections

**`eval_jobs`** — Video generation jobs

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique job ID (millisecond timestamp) |
| `prompt` | string | Generation prompt text |
| `prompt_id` | string | Batch identifier for grouping |
| `categories` | string[] | Auto-generated tags |
| `ratio` | string | `"16:9"` or `"9:16"` |
| `timestamp` | float | Creation time |
| `initiation_time` | float | When generation started |
| `start_image_url` | string | First-frame image (I2V) |
| `end_image_url` | string | Last-frame image |
| `reference_image_url` | string | Style reference |
| `reference_images` | string[] | Multiple references (R2V) |
| `results` | map | `model_id` -> `{ status, url, latency, error }` |
| `generation_history` | map | `model_id` -> previous result archives |

**`votes`** — Evaluation ratings

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique vote ID |
| `job_id` | string | References batch/prompt |
| `winner_side` | string | `"a"` or `"b"` |
| `winner_model` | string | Winning model ID |
| `loser_model` | string | Losing model ID |
| `scores` | map | `{ motion, prompt, aesthetic, expressiveness, sync }` (1-10) |
| `justification` | string | Free-text evaluator comment |
| `timestamp` | float | When vote was cast |
| `ldap` | string | Evaluator identifier |

**`prompts`** — Submission queue

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique prompt ID |
| `text` | string | Prompt text |
| `categories` | string[] | Tags |
| `models` | string[] | Models to generate with |
| `status` | string | `"pending"`, `"generating"`, `"complete"` |

**`slideware_feedback`** — Slideware picks & comments (keyed by `batch_name__tier`)

### Cloud Storage Layout

```
gs://project-pulse/
  fal_<timestamp>_<filename>.mp4         # FAL-generated videos
  veo_sdk_<timestamp>.mp4                # Veo SDK-generated videos
  veo_input_<timestamp>_<filename>       # Input images for Veo I2V
  veo_ref_<timestamp>_<filename>         # Reference images for Veo R2V
  uploads/<timestamp>_<filename>         # User-uploaded files
  (Vertex storageUri output)             # Direct Veo output
```

Bucket is private — all access via `/api/media` proxy or ADC.

---

## Model Registry (models.json)

50+ model configurations across providers:

**Veo (Vertex AI):**
- `veo-3-1-001` — T2V, I2V (active)
- `veo-3-1-fast-001` — T2V, I2V (active)
- `veo-3-1-lite-001` — T2V, I2V (active)
- `veo-3-1-preview` / `veo-3-1-fast-preview` — T2V, I2V, R2V (active)
- `veo-3-1-preview-r2v` / `veo-3-1-fast-preview-r2v` — R2V (active)

**Seedance (FAL):**
- `seedance-2-0` — T2V, I2V (active)
- `seedance-2-0-fast` — T2V, I2V (active)
- `seedance-1-5` / `seedance-1-fast` — T2V, I2V (inactive)

**Kling (FAL):**
- `kling-3-pro` / `kling-3-standard` — T2V, I2V, R2V (inactive)
- `kling-o3-pro` / `kling-o3-standard` — T2V, I2V, R2V (inactive)
- `kling-2-6` / `kling-2-5` — T2V, I2V (inactive)

**Grok (FAL):**
- `grok-imagine` — T2V, I2V (active)

Toggle models via `/api/models/{id}/toggle` without code changes.

---

## Environment Variables

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `GCP_PROJECT_ID` | `vital-octagon-19612` | yes | Google Cloud project |
| `GCS_BUCKET_NAME` | `project-pulse` | yes | GCS bucket for video storage |
| `FAL_KEY` | — | yes | FAL.ai API key |
| `OUTPUT_GCS_BUCKET` | `gs://{GCS_BUCKET_NAME}/` | no | Vertex AI output bucket URI |
| `DRIVE_PARENT_FOLDER_ID` | `0ABrvNdvu6qXtUk9PVA` | no | Shared Drive folder for video uploads |
| `DRIVE_IMPERSONATE_USER` | — | no | Email for domain-wide delegation |
| `PORT` | `8080` | no | Server port |
| `NEXT_PUBLIC_API_URL` | `""` (relative) | no | Frontend API base URL |

---

## Local Development

### Prerequisites

- Python 3.12+
- Node.js 20+
- `gcloud` CLI (authenticated)
- GCP project with Firestore + Cloud Storage enabled
- FAL API key

### Setup

```bash
# 1. Clone
git clone https://github.com/gauravz7/mediasxs.git
cd mediasxs/project-pulse

# 2. Backend
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Authenticate GCP
gcloud auth application-default login

# 4. Set environment
export FAL_KEY=your-fal-api-key
export GCP_PROJECT_ID=your-project-id

# 5. Start backend
uvicorn main:app --reload --port 8080

# 6. Start frontend (separate terminal)
cd ../frontend
npm install
npm run dev
```

**Endpoints:**
- Frontend: http://localhost:3000
- Admin: http://localhost:3000/admin
- API docs: http://localhost:8080/docs
- Slideware: http://localhost:8080/slideware

---

## Deployment

### Docker

**Unified build** (recommended) — single container serves frontend + backend:

```dockerfile
# Stage 1: Build frontend static export
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
ENV NEXT_PUBLIC_API_URL=""
RUN npm run build

# Stage 2: Backend + static frontend
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend /app/
COPY --from=frontend-builder /app/frontend/out /app/static
ENV PORT=8080
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
```

### Cloud Run

```bash
gcloud run deploy project-pulse-backend \
  --source . \
  --region us-central1 \
  --service-account claude@vital-octagon-19612.iam.gserviceaccount.com \
  --allow-unauthenticated \
  --memory 2Gi \
  --timeout 3600 \
  --set-env-vars "FAL_KEY=<key>,GCP_PROJECT_ID=vital-octagon-19612"
```

**`.gcloudignore`** excludes: `.git/`, `*.md`, `node_modules/`, `.next/`, `out/`, `venv/`, `__pycache__/`, `.env`, `signing_keys.json`, `backups/`.

---

## Service Account Permissions

The Cloud Run SA (`claude@vital-octagon-19612.iam.gserviceaccount.com`) requires:

| Permission | Resource | Purpose |
|------------|----------|---------|
| `roles/storage.objectViewer` | `project-pulse` bucket | Read videos/images |
| `roles/storage.objectCreator` | `project-pulse` bucket | Upload videos |
| `roles/datastore.user` | Project | Firestore read/write |
| `roles/aiplatform.user` | Project | Vertex AI / Veo generation |
| `roles/iam.serviceAccountTokenCreator` | Self | Signed URLs on Cloud Run |
| Content Manager | Shared Drive `0ABrvNdvu6qXtUk9PVA` | Drive video uploads |

---

## Troubleshooting

**Video generation fails:**
- Verify `FAL_KEY` is set and valid
- Check GCS bucket exists and SA has write access
- Confirm model `is_active` in `/api/models`
- Review per-model errors at `/api/admin/jobs/{id}/status`
- Retry via admin console or `POST /api/admin/jobs/{id}/retry`

**Videos don't play / URL errors:**
- All GCS access must go through `/api/media` proxy
- Verify SA has `storage.objects.get` permission
- Check proxy returns 200: `curl /api/media?url=gs://...`

**Firestore quota exceeded:**
- Reduce admin console polling (default: 30s)
- Prune old votes: `POST /api/admin/votes/prune?keep=50`

**Drive uploads fail:**
- Verify SA is Content Manager on the Shared Drive
- Check `DRIVE_PARENT_FOLDER_ID` points to valid folder
- Use `--dry-run` with `bulk_drive_upload.py` to diagnose

**Slides generation errors:**
- Videos must be uploaded to Drive first (via `bulk_drive_upload.py`)
- Verify presentation ID in Firestore `config/slides_presentation`
- Use `--new` flag to rebuild from scratch
