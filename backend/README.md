# Project Pulse Backend

> Module-by-module map of the code (what each router owns, every endpoint, and which are admin-gated): [`../docs/api/BACKEND_MODULES.md`](../docs/api/BACKEND_MODULES.md).

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
  - [Data Intake](#data-intake-prompts--customer-supplied-outputs)
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

`main.py` is **application assembly only** (~115 lines): the `FastAPI` app, the
validation handler, CORS, every `include_router`, the static mount, and the
back-compat re-exports that `model_resolver.py`, `tts_pipeline.py` and the test
suite rely on. Every handler lives in a router module.

Routers are registered **before** the static catch-all mount, so `/api/*` always
beats the compiled Next.js UI.

| File | Purpose |
|------|---------|
| `main.py` | App assembly, router registration order, static mount |
| `config.py` | Env constants (`GCP_PROJECT_ID`, `GCS_BUCKET_NAME`, `SXS_*_COLLECTION`) + `normalize_gcs_url` |
| `registry.py` | The cross-modality model registry; `PROVIDER_TRANSPORT` enforces Google→Vertex / non-Google→FAL |
| `store.py` | Legacy `Job`/`Vote`/`Prompt` documents and managers (the pre-SxS `eval_jobs` flow) |
| `auth.py` | `require_admin` and the stateless admin token |
| `tagging.py` / `generation.py` | Gemini auto-tagging tasks / the legacy multi-model generation engine |
| `video_routes.py` | `/api/sxs/*` — the live video modality |
| `image_routes.py` / `tts_routes.py` | The image and TTS modalities |
| `intake_routes.py` + `intake.py` | The six data-intake endpoints and the URL-rehosting logic behind them |
| `models_routes.py` / `admin_routes.py` | `/api/models`; login, prompts, tags, Sheets, legacy jobs view |
| `analytics_routes.py` | Stats, leaderboards, `/api/benchmark/winmap`, `/api/analytics/agreement` |
| `media_routes.py` | `/api/health` and the authenticated `/api/media` GCS proxy |
| `slides_routes.py` / `legacy_routes.py` | Slides + slideware; the pre-multi-modality endpoints |
| `model_resolver.py` | Shared "is this model registered and active" gate |
| `sxs_pipeline.py` / `image_pipeline.py` / `tts_pipeline.py` | Per-modality job creation + generation |
| `video_evaluator_sdk.py` / `image_evaluator.py` / `tts_evaluator.py` | The LLM-as-judge per modality |
| `providers/vertex_provider.py` | Google Vertex AI / Veo video generation + Gemini tagging |
| `providers/fal_provider.py` | FAL.ai provider — Kling, Seedance, Grok video generation |
| `util/gcs_utils.py` | GCS upload/download, signed URL generation, URL normalization |
| `util/drive_utils.py` | Google Drive video uploads to Shared Drive |
| `util/sheets_utils.py` | Google Sheets read/write for batch processing |
| `util/ratelimit.py` | Process-wide concurrency cap (≤3) on generative calls, with 429 backoff |
| `models_builtin.json` | Committed registry seed |
| `models.json` | Gitignored admin-API overlay, merged on top of the seed |

Per-endpoint detail for every module is in
[`../docs/api/BACKEND_MODULES.md`](../docs/api/BACKEND_MODULES.md).

### Tests

```bash
cd backend && python -m pytest tests -q     # ~4s, hermetic — no GCP credentials needed
```

`tests/` covers the intake APIs (registry gate, job-doc shapes, all six endpoints
end to end) and the FAL-backed ElevenLabs request shaping. `conftest.py` stubs
Firestore, GCS, the providers and the Gemini tagging calls — **no test may hit a
live API.**

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

### Data Intake (prompts + customer-supplied outputs)

The standard, documented way to get a customer's data into a duel — for all
three modalities. Customer-facing narrative version, with fuller examples:
**[`docs/api/DATA_INTAKE.md`](../docs/api/DATA_INTAKE.md)**. What follows is the
formal spec: every input field, every output field, every status code.

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/intake/models` | none | Model names accepted below, per modality |
| POST | `/api/sxs/prompts` | admin | **BYOP** — run video cases on named models (N-way) |
| POST | `/api/image/prompts` | admin | **BYOP** — run image cases on a named pair |
| POST | `/api/tts/prompts` | admin | **BYOP** — run TTS cases on a named pair |
| POST | `/api/sxs/outputs` | admin | **BYOO** — register customer-generated video |
| POST | `/api/image/outputs` | admin | **BYOO** — register customer-generated images |
| POST | `/api/tts/outputs` | admin | **BYOO** — register customer-generated audio |

`sxs` = video. Implemented in `intake_routes.py` (routing + validation) and
`intake.py` (rehost + job-doc construction); model names resolve through
`model_resolver.py` against the shared registry — an unknown or inactive name is
a `400`, never a job that silently produces nothing.

Auth is the standard admin token: `X-Admin-Token: <token>` from
`POST /api/admin/login`. Content type is `application/json` on every POST.

#### `GET /api/intake/models`

**Input** (query string):

| param | type | default | meaning |
|---|---|---|---|
| `modality` | `"video" \| "image" \| "tts"` | all three | restrict the listing |
| `active_only` | bool | `true` | `false` also lists deactivated models |

**Output** `200` — `{"models": ModelInfo[]}`:

| field | type | notes |
|---|---|---|
| `id` | string | **the name you pass** in `models` / `outputs` keys |
| `name` | string | display label |
| `modality` | `"video" \| "image" \| "tts"` | derived from `type` |
| `type` | `"t2v" \| "i2v" \| "r2v" \| "t2i" \| "tts"` | video types must match the case |
| `provider` | string | dispatch key: `vertex`, `omni`, `fal`, `gemini`, `gpt`, `mai`, `gemini_tts`, `elevenlabs` |
| `transport` | `"vertex" \| "fal"` | Google → Vertex AI, everything else → FAL |
| `quality` | string \| null | GPT-image tier (`low`/`medium`/`high`), else null |
| `is_active` | bool | inactive models are rejected by both POST paths |

```json
{"models": [{"id": "elevenlabs-v3", "name": "ElevenLabs (v3)", "modality": "tts",
             "type": "tts", "provider": "elevenlabs", "transport": "fal",
             "quality": null, "is_active": true}]}
```

#### `POST /api/{sxs,image,tts}/prompts` — BYOP

You supply prompts + model names; the platform generates, judges, and files the
duel.

**Input** (request body):

| field | type | required | default | meaning |
|---|---|---|---|---|
| `models` | string[] | **yes** | — | registry ids, applied to **every** case in the request |
| `cases` | object[] | **yes** | — | per-modality case objects, below |
| `run_eval` | bool | no | `true` | run the AI judge after generation |
| `batch_id` | string \| null | no | `"{modality}_intake_{epoch}"` | your own grouping label |

Models per duel: **video any number ≥ 1** (`results` is keyed by model id),
**image and TTS exactly 2** (the doc is two-sided — `results` keyed `A`/`B` with
a `side_map`). Passing 1 or 3 to image/TTS is a `400`, not a truncation.

**Case object — video** (`/api/sxs/prompts`):

| field | type | required | notes |
|---|---|---|---|
| `id` | string | **yes** | unique case id. Embeds the customer name — the UI only ever shows the last 4 chars (`maskPid()`) |
| `prompt` | string | **yes** | generation instruction |
| `modality` | string | **yes** | `T2V`, `I2V`, `FLF2V`, `V2V`, `Ref2V` → registry types `t2v`/`i2v`/`r2v`. Every named model must match, or that case is skipped |
| `customer` | string | no | analytics grouping key |
| `aspect_ratio` | string | no | `"16:9"` default. On `/outputs`, `ratio` is accepted as an alias |
| `duration` | number \| null | no | seconds |
| `reference_images` | string[] | i2v / r2v | URLs — first frame, last frame, subject refs |
| `reference_videos` | string[] | v2v / r2v | URLs |
| `categories` | string[] | no | analytics tags; `tags` / `category` accepted as aliases |

**Case object — image** (`/api/image/prompts`). T2I vs I2I is a property of the
**case**, not the model — one registered `t2i` model serves both:

| field | type | required | notes |
|---|---|---|---|
| `id` | string | **yes** | unique case id |
| `prompt` | string | **yes** | generation or edit instruction |
| `mode` | string | no | `"t2i"` (default) or `"i2i"`; `modality` accepted as an alias, `edit`/`image-to-image` as `i2i` aliases |
| `input_image` | string | **i2i** | source-image URL; `reference_image` / `input_images[0]` accepted. Rehosted into our bucket so the judge can read it |
| `aspect_ratio` | string | no | e.g. `"1:1"` |
| `resolution` | string | no | free-form |
| `customer`, `categories` | string / string[] | no | as above |

An `i2i` case adds an **edit-fidelity** criterion to the judge.

**Case object — TTS** (`/api/tts/prompts`). Single vs multi-speaker is likewise
a property of the **case** — both engines render whichever it asks for:

| field | type | required | notes |
|---|---|---|---|
| `id` | string | **yes** | unique case id |
| `text` | string | **yes** | the script. Multi-speaker: one `Name: line` per line |
| `mode` | string | no | `"single"` (default) or `"multi"` |
| `speakers` | object[] | **multi** | `[{"name": "Priya"}, …]`; each distinct name gets its own voice, in order of first appearance |
| `voice` | string | no | single-speaker only — curated name (`George`, `Sarah`, …) or a raw voice id |
| `language` | string | no | BCP-47-ish. **Autodetected from `text` when omitted**; a mixed tag like `hi-en` generates in `hi` and keeps the full tag for filtering |
| `style_prompt` | string | no | delivery direction; also drives ElevenLabs' stability tier |
| `customer`, `categories` | string / string[] | no | categories auto-tag from language + industry when omitted |

Inline audio tags (`[excited]`, `[whispers]`) are passed to ElevenLabs v3 and
stripped for engines that don't support them.

Generation is **asynchronous** — the call returns as soon as the job docs exist.
Poll `GET /api/{sxs,image,tts}/jobs` and watch `results[*].status` and
`auto_eval_status`.

#### `POST /api/{sxs,image,tts}/outputs` — BYOO

You supply prompts + URLs to media you already generated; the platform rehosts,
judges, and files the duel.

**Input** (request body):

| field | type | required | default | meaning |
|---|---|---|---|---|
| `cases` | object[] | **yes** | — | same case objects as BYOP, **plus** `outputs` |
| `run_eval` | bool | no | `true` | run the AI judge on the supplied media |
| `batch_id` | string \| null | no | `"{modality}_intake_{epoch}"` | grouping label |
| `source_label` | string | no | `"api ingest"` | provenance, stored as `imported_from` |

There is **no request-level `models` list** — each case carries its own
`outputs` manifest, because a customer export is rarely uniform (one case may
compare A vs B, the next B vs C). A `models` key sent at request level is
ignored.

**`outputs` manifest** — keys are registry model ids; the value is either a URL
string (shorthand) or an object:

| field | type | required | notes |
|---|---|---|---|
| `url` | string | **yes** | `https://`, `http://`, or `gs://` |
| `latency_ms` | number \| null | no | the customer's own generation time — feeds latency analytics. Omit rather than guess; it is never invented |
| `metadata` | object | no | free-form, stored on the result and never interpreted |

Same per-duel counts as BYOP: video N-way, image/TTS exactly 2 keys.

```json
{"cases": [{"id": "acme_i001", "mode": "t2i", "prompt": "a red maple leaf",
            "outputs": {"gemini-3-pro-image": "https://acme.example.com/g.png",
                        "gpt-image-2-high": {"url": "gs://acme-share/o.png",
                                             "latency_ms": 4200,
                                             "metadata": {"seed": 12345}}}}],
 "run_eval": true, "source_label": "Acme Q3 export"}
```

**URL handling.** Every supplied URL — outputs, `reference_images`,
`reference_videos`, `input_image` — is downloaded and **rehosted into our GCS
bucket** (`sxs/ingest/`, `images/ingest/`, `audio/ingest/`), because signed
links expire and both the judge and the `/api/media` proxy read through GCS. A
URL already in our bucket is passed through untouched. Rehosting is
**synchronous**, so split very large imports across a few requests. An
unreachable URL fails only its own case, reported in `skipped`.

#### Response envelope (all six endpoints)

| field | type | meaning |
|---|---|---|
| `status` | `"ok" \| "failed"` | `"failed"` only when *nothing* could be created |
| `batch_id` | string | echoed, or the generated one |
| `job_ids` | string[] | Firestore doc ids created, in case order |
| `count` | int | `len(job_ids)` |
| `skipped` | object[] | one entry per rejected case: `{index: int, id: string, reason: string}` |

```json
{"status": "ok", "batch_id": "image_intake_1785914380",
 "job_ids": ["img_acme-i001_1785914356594_652"], "count": 1,
 "skipped": [{"index": 3, "id": "acme_004",
              "reason": "'ghost-model' is not a registered model"}]}
```

**One bad row never aborts the batch** — a 500-case upload with two malformed
rows produces 498 jobs and two `skipped` entries. `skipped[].id` falls back to
`"(case #N)"` when the case has no `id`.

#### Status codes

| code | when | body |
|---|---|---|
| `200` | at least one case was accepted (or all were skipped, with `status: "failed"`) | the envelope above |
| `400` | request-level failure: no cases, unusable model name, wrong model count for a two-sided modality, unknown `modality` query value | `{"detail": ...}` — string, or the structured object below |
| `401` | missing or wrong `X-Admin-Token` | `{"detail": "Admin authentication required"}` |
| `422` | body doesn't parse (e.g. `models` omitted on `/prompts`) | FastAPI validation array |
| `500` | `ADMIN_PASS` not configured on the server | `{"detail": "ADMIN_PASS not configured on server"}` |

An unusable model name reports **every** problem at once, and lists what *is*
available:

```json
{"detail": {"error": "Unusable model(s) requested.",
            "problems": ["'ghost-model' is not a registered model",
                         "'gemini-3-pro-image' is a image model, not tts"],
            "available": ["elevenlabs-v3", "gemini-3.1-flash-tts-preview"]}}
```

Wrong count on a two-sided modality is a plain-string detail:
`{"detail": "tts duels are two-sided: pass exactly 2 models, got 1."}`

When the same problem hits a single case rather than the whole request, that
structured detail is flattened into one `skipped[].reason` string instead.

#### What the endpoints write

Both paths produce an ordinary job doc — indistinguishable from a
platform-generated one in the arena, judge, and analytics, except for
provenance. Every doc carries `source: "sxs_auto"` (every list/pair endpoint
filters on it) and `auto_eval_status` — `"pending"` normally, `"skipped"` when
`run_eval: false`, which makes the job human-votable but unjudged.

| modality | collection | id prefix | `results` keyed by |
|---|---|---|---|
| video | `sxs_jobs` | `adm_` (BYOP) / `ing_` (BYOO) | model id |
| image | `image_jobs` | `img_` | `"A"` / `"B"`, with `side_map` + `side_specs` |
| tts | `tts_jobs` | `tts_` | `"A"` / `"B"`, with `side_map` |

BYOP video docs are marked `origin: "admin"`. **BYOO docs of every modality**
carry `origin: "ingest"` plus `imported_from: <source_label>`, and each result
object is:

```json
{"status": "success", "model": "Gemini 3 Pro Image", "engine": "gemini-3-pro-image",
 "url": "gs://project-pulse/images/ingest/...", "gcs_url": "gs://...",
 "result": {"url": "gs://..."}, "error": null, "ingested": true,
 "latency_ms": 4200, "metadata": {"seed": 12345}}
```

(`engine` on image/TTS only; `latency_ms` and `metadata` only when supplied.)

#### Auto-tagging

`categories` is optional on both intake paths — `intake.autotag_job` runs as a
background task after the response and tags the job from its prompt, using the
same tagger the modality's generated path uses, so a case tags identically
whichever way it arrived:

| modality | tagger | supplied `categories` |
|---|---|---|
| video | `vertex_provider.generate_tags_with_gemini` over the prompt + rehosted reference imagery | kept; the tagger only fills a gap |
| image | `image_taxonomy.classify_image_categories` (fixed 30-category taxonomy) | taxonomy still wins; yours preserved under `categories_raw` |
| TTS | `_detect_language` + `_voice_categories`, inside `build_tts_job_doc` | kept |

Best-effort: a tagger failure leaves the job untagged but created, votable and
judged. `POST /api/admin/backfill-tags` re-tags anything missing categories.

#### Known limits

- **Image and TTS duels are structurally two-sided** — comparing three image
  models means three pairwise requests.
- **The registry is not durable** (see [Model Registry](#model-registry-modelsjson))
  — models added via `POST /api/models` are lost when Cloud Run recycles the
  instance, and with them the ability to name those models here.

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

**Image (T2I / I2I)** — one entry serves both modes; the pipeline switches on
whether the case has an `input_image`:
- `gemini-3.1-flash-image`, `gemini-3.1-flash-lite-image`, `gemini-3-pro-image` — Vertex
- `gpt-image-2-low` / `-medium` / `-high` — FAL, same `model_id` with `quality` set
- `mai-image-2.5` — FAL

**TTS:**
- `gemini-3.1-flash-tts-preview` — Vertex
- `elevenlabs-v3` — FAL (`fal-ai/elevenlabs/tts/eleven-v3`)

Toggle models via `/api/models/{id}/toggle` without code changes.

### Two files, one registry

| file | committed? | role |
|---|---|---|
| `models_builtin.json` | **yes** | the seed — every model the platform ships with |
| `models.json` | no (gitignored) | the overlay written by the admin API |

`RegistryManager` loads the builtin file, then applies the overlay on top, so a
fresh checkout and a recycled Cloud Run instance both come up with a working
registry. Deleting a builtin model **deactivates** it rather than removing it —
a true delete would silently come back on the next restart.

### `transport` — Google via Vertex, everything else via FAL

Each entry carries a `provider` (the **dispatch key** the pipelines switch on)
and a derived `transport` of `vertex` or `fal`, validated on write against
`main.PROVIDER_TRANSPORT`:

| provider | transport |
|---|---|
| `vertex`, `omni`, `gemini`, `gemini_tts` | `vertex` |
| `fal`, `gpt`, `mai`, `elevenlabs` | `fal` |

An unrecognized provider is rejected at registration. Registry `type`
(`t2v`/`i2v`/`r2v` → video, `t2i`/`i2i` → image, `tts` → tts) is what scopes a
model to one modality's endpoints.

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

### Tests

```bash
cd backend && python -m pytest tests -q      # ~3s, no credentials needed
```

`backend/tests/` covers the model registry gate, the intake job-doc shapes, and
the six intake endpoints end to end through the app. The suite is **hermetic** —
`tests/conftest.py` stubs Firestore, GCS, the provider APIs, and the two Gemini
auto-tagging calls that TTS job creation makes, so it runs offline and
deterministically. Nothing else in the backend has automated tests yet.

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
