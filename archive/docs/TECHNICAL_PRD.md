# GenMedia SxS — Technical Product Requirements Document (PRD)

**Product:** GenMedia SxS (internal codename *Project Pulse*)
**Type:** Technical PRD
**Status:** Living document — reflects the `genmedia-sxs-v2` build (image + video + TTS)
**Last updated:** 2026-07-22
**Owner:** GenMedia Evaluation Program

---

## 1. Overview

### 1.1 Summary
GenMedia SxS is an internal **blind side-by-side (SxS) evaluation platform** for generative-media models across three modalities — **image, video, and text-to-speech (TTS)**. It runs head-to-head, model-blind A/B comparisons produced from the same prompt, and scores each pair through two independent channels:

1. **Human evaluators** — blind per-metric 1–5 scoring plus an overall winner (A / B / tie).
2. **Automatic LLM-as-judge** — a multimodal Gemini model on Vertex AI scores each pair on modality-specific rubrics.

Results are aggregated into an analytics layer that reports win-rates with 95% Wilson confidence intervals, generation latency, **human ↔ AI-judge agreement**, and a segmented **win-map** showing where model families (specifically Google models) win by category, language, and modality.

### 1.2 Problem statement
Teams shipping generative-media models need a defensible, repeatable way to answer *"is model A better than model B, and where?"* Ad-hoc side-by-side comparisons are biased (raters see model identities), inconsistent (no fixed rubric), unscalable (manual), and lack statistical rigor (no confidence intervals, no human/AI agreement signal). GenMedia SxS provides a controlled arena, a fixed rubric per modality, an automatic judge to scale coverage, and statistics that quantify significance.

### 1.3 Goals
- Provide **blind, randomized** A/B arenas for image, video, and TTS.
- Capture **structured human judgments** (per-metric + overall winner) with low friction.
- Provide an **automatic multimodal judge** that scales evaluation coverage beyond sparse human votes.
- Quantify **model win-rates with statistical confidence** (Wilson intervals), sliced by category / language / modality.
- Measure **human/AI-judge agreement** to validate the automatic judge.
- Support a **controlled taxonomy** for consistent tagging and filtering.
- Support **multilingual TTS** (English, Hindi, Hinglish, Hindi-Bengali, with multilingual fallback).
- Deploy as a **single unified service** that is cheap to run and simple to operate.

### 1.4 Non-goals
- Not a model-training or fine-tuning system (it produces evaluation signal consumed elsewhere).
- Not a general-purpose media asset manager or CMS.
- Not a public product — it is internal, gated by an evaluator LDAP handle and admin credentials.
- No automated test suite or CI is currently part of the product scope (see §16).

---

## 2. Users & personas

| Persona | Needs | Surface |
|---|---|---|
| **Evaluator** | Cast fast, blind, structured votes; see personal progress and leaderboard standing. | `/image-sxs`, `/video-sxs`, `/tts-sxs`, `/leaderboard` |
| **Analyst / stakeholder** | Understand win-rates, where a family wins, latency, and judge reliability. | `/analytics`, `/ai-evals` |
| **Admin / operator** | Upload evaluation batches, manage the model registry, monitor generation jobs, retry failures, generate slide decks. | `/admin` |

Access model:
- **Evaluators** identify with an **LDAP handle** (free text) — no password. Voting is attributed to the handle; `anonymous` / `global` handles are excluded from the leaderboard.
- **Analytics** is gated behind a **10-vote wall** per evaluator (progress bar drives engagement).
- **Admins** authenticate with a username/password (`ADMIN_USER` / `ADMIN_PASS`) exchanged for a token used in the `X-Admin-Token` header.

---

## 3. Product surface (routes / screens)

Frontend routes (Next.js App Router, `frontend/src/app/`):

| Route | Purpose |
|---|---|
| `/` | Landing hub linking to the three arenas + analytics. |
| `/image-sxs` | Blind human image A/B arena. |
| `/video-sxs` | Blind human video A/B arena. |
| `/tts-sxs` | Blind human TTS A/B arena. |
| `/ai-evals` (a.k.a. `/ai-ratings`) | All AI-judge verdicts: per-model scores + winner. |
| `/analytics` | Win-rates + CIs, latency, human/AI agreement, win-map. |
| `/leaderboard` | Top evaluators by completed-vote count. |
| `/admin` | JSON batch upload, model registry, generations monitor, slide export. |

Key UI behaviors:
- **Blind rendering:** model identities are hidden; left/right (A/B) assignment is randomized per pair-serve (`random.shuffle` on the server). Identities are only revealed after a vote.
- **Play Both** (video/TTS): synchronized playback of both variants.
- **Skip:** non-evaluable pairs (both broken, identical) can be skipped without a vote.
- **PID masking:** prompt/case IDs embed customer names; the UI must only ever render the **last 4 characters** via `maskPid()` (`frontend/src/lib/api.ts`). Never surface a full prompt ID user-facing.

---

## 4. Functional requirements by modality

Each modality is an **isolated vertical**: its own generation pipeline, AI judge/evaluator, HTTP routes, and Firestore collections. They rarely share code.

| Modality | Routes | Pipeline | Evaluator | Firestore collections (env-configurable) |
|---|---|---|---|---|
| **Video** (internally "sxs") | `/api/sxs/*` — inline in `main.py` | `sxs_pipeline.py` | `video_evaluator_sdk.py` | `SXS_COLLECTION` (`sxs_jobs`), `SXS_VOTES_COLLECTION`, `SXS_RUNS_COLLECTION` |
| **Image** | `image_routes.py` (router) | `image_pipeline.py` | `image_evaluator.py` (+ `image_taxonomy.py`) | `IMAGE_COLLECTION` (`image_jobs`), `IMAGE_VOTES_COLLECTION` (`image_votes`) |
| **TTS** | `tts_routes.py` (router) | `tts_pipeline.py` | `tts_evaluator.py` | `TTS_COLLECTION` (`tts_jobs`), `TTS_VOTES_COLLECTION` (`tts_votes`) |

### 4.1 Image
- **Modes:** `t2i` (text-to-image) and `i2i` (image edit).
- **Matchups:** Gemini image (Pro / Flash / Flash-Lite) vs GPT-image-2 (low / medium / high) vs MAI-Image. The matchup is resolved from the case via `resolve_matchup` / `list_matchups` in `image_pipeline.py`.
- **Case input (admin JSON):** `{ id, mode: "t2i"|"i2i", prompt, matchup, aspect_ratio?, input_image?, categories? }`.
- **Tagging:** categories chosen strictly from the 30-item controlled taxonomy (§6).

### 4.2 Video
- **Modalities:** `t2v` (text-to-video), `i2v` (image-to-video), `r2v` (reference/video-to-video).
- **Matchup (current build):** Seedance vs Omni head-to-head (see `create_sxs_job`; each job stores `results.{SEEDANCE_KEY}` and `results.{omni_key}`). Broader registry (Veo/Kling/Grok) exists in `models.json` for the admin-driven multi-model flow.
- **Case input:** `{ id, prompt, modality: "t2v"|"i2v"|"r2v", aspect_ratio?, reference_images?, reference_videos?, categories? }`.
- **Auto-tagging:** if a case has no categories/tags, the pipeline calls `generate_tags_with_gemini` (falls back to text-only if reference images are invalid).

### 4.3 TTS
- **Modes:** `single` (single-speaker) and `multi` (multi-speaker dialogue).
- **Matchup:** Gemini TTS vs ElevenLabs v3.
- **Languages:** English, Hindi, Hinglish, Hindi-Bengali, with a graceful multilingual fallback for any other language (`ELEVENLABS_FALLBACK_MODEL`).
- **Case input:** `{ id, text, voice, language, style_prompt?, mode?: "single"|"multi", speakers?, el_voice?, categories? }`.

---

## 5. Evaluation system

Every job is scored two ways: **human** (blind vote) and **AI judge** (multimodal LLM). Both map their A/B verdict back to the concealed engine identity via the job's `side_map`.

### 5.1 Human voting
- **Serve:** `GET /api/{sxs,image,tts}/pair` returns a random ready pair (≥2 successful sides), with optional filters (`tag`/category, `prompt_id`, `search` on prompt text). Media URLs are signed GCS URLs; A/B order is randomized server-side.
- **Vote:** `POST /api/{sxs,image,tts}/vote` records `{ job_id, winner_side, winner_model, loser_model, scores{}, justification, ldap, timestamp }`.
- **Idempotency:** duplicate votes from the same `ldap` on the same `job_id` within a **20-second window** are ignored (`status: duplicate_ignored`) to defend against double-clicks/retries.
- **Human rubric (video, evaluator-facing):** Prompt Adherence, Motion Quality, Aesthetic Quality, Physics & Cohesion, Audio Expressiveness, Audio-Visual Sync (see `docs/EVALUATOR_GUIDELINES.md`).

### 5.2 AI judge (LLM-as-judge)
Shared judge properties across modalities:
- Multimodal **Gemini on Vertex AI**, lazily-constructed client, 10-minute request timeout.
- `temperature = 0.1`, JSON-constrained output (`response_mime_type=application/json` + schema), retry-with-backoff wrapper.
- Video judge additionally runs with `thinking_level = HIGH` and a `CRITICAL AUDITING PROTOCOL` that forces evidence + timestamps and grounds against verified video metadata (duration/fps) to prevent hallucination.
- Default judge models (env-overridable): image `IMAGE_EVAL_MODEL` (`gemini-3.5-flash`), TTS `TTS_EVAL_MODEL` (`gemini-3.5-flash`), video `EVAL_MODEL` (`gemini-3.1-pro-preview`).

**Image rubric** (per side, 1–5): `prompt_following`, `aesthetic`, `detail`, `artifact_free`, plus `edit_fidelity` for `i2i` only. Output: per-side scores + comment, `winner` (A/B/tie), `justification`. Stored under `ai_eval` with `winner_engine` resolved via `side_map`.

**TTS rubric** (per side, 1–5): `naturalness`, `style_adherence`, `expressiveness`, `pacing`, `pronunciation_clarity`. Output: per-side scores + comment, `winner`, resolved `winner_engine`. Stored under `ai_eval`.

**Video judges** (`video_evaluator_sdk.py`):
- **Core-5** (`run_core5_evaluation`, the primary per-video deliverable) — integer 1–5 on: `prompt_adherence`, `visual_quality`, `motion_physics`, `temporal_consistency`, `audio_visual_sync`; `overall_score` = mean of the five; `critical_flaws[]`. Maximum strictness (a 5 requires a genuinely flawless axis). Reference images/videos, when present, factor into temporal_consistency / prompt_adherence / visual_quality.
- **Creative Director pairwise** (`run_director_pairwise`) — head-to-head A vs B verdict (`verdict: A|B`, reasoning, per-category comparative critique). This verdict is the authoritative winner for video jobs; win-map/agreement fall back to highest Core-5 `overall_score` for older jobs lacking a director verdict.
- **Specialized ported judges** (available): Canva, product-ad, human-consistency (0–3 per axis, sum ≤9), storytelling, audio-visual sync.

- **Error handling:** any judge failure records `auto_eval_status = error` with the message; the pipeline swallows it so generation/serving is unaffected.

---

## 6. Controlled taxonomy

`image_taxonomy.py` defines a **30-category controlled vocabulary** (order = UI display order): 15 canonical buckets (Anime, Cartoon & Illustration, Traditional Art, General & Photorealistic, Nature & Landscapes, People: Portraits, People: Groups & Activities, Physical Spaces, Vintage & Retro, Futuristic & Sci-Fi, Fantasy & Mythical, Graphic Design & Digital Rendering, Text & Typography, UI/UX Design, Commercial) plus 15 domain subcategories (Comics & Manga, 3D Render & CGI, Storyboard & Concept Art, Character Design, Gaming & Game Art, Product & Packaging, Food & Beverage, Fashion & Apparel, Automotive & Vehicles, Animals & Wildlife, Architecture & Interiors, Logos & Branding, Infographics & Diagrams, Abstract & Patterns, Macro & Close-up).

`classify_image_categories(prompt, mode)` maps a prompt to **1–3 labels chosen strictly from the vocabulary** using `gemini-2.5-flash`, with a keyword-based fallback if the LLM call fails. Used to tag new jobs and re-tag existing ones, replacing older free-form tags.

---

## 7. Analytics & statistics

### 7.1 Latency — `GET /api/analytics/latency`
Average generation latency per `(modality, model)` across all modalities, normalized to **seconds** (video stores `latency` in s; image/TTS store `latency_ms`). Only `status == success` results are counted. Returns rows sorted by modality order (`t2v, i2v, r2v, t2i, i2i, tts`) then sample count, each with `avg_latency_s` and `samples`.

### 7.2 Win-map — `GET /api/benchmark/winmap?min_n=10`
"Where does Google win?" Aggregates **AI-judge verdicts** across image, TTS, and video, restricted to **Google-vs-competitor pairs** (exactly one Google engine + one competitor; family detection via `_is_google_engine` — matches gemini/imagen/veo/omni/nano/banana/doubao-google). Reports Google's win-rate with **95% Wilson score confidence intervals** and `n`, sliced by `category`, `language`, and `modality` (plus `overall`).
- Thin segments (`n < min_n`, default 10) are dropped — a CI on tiny n is not meaningful.
- Per segment: `verdict = lead` if CI low > 50%, `trail` if CI high < 50%, else `tie`. `leads` and `trails` lists surface segments whose interval clears 50%.
- Wilson implementation (`_wilson(k, n, z=1.96)`) returns `(low, p, high)`.
- Uses the AI judge specifically because human votes are sparse; should be read alongside agreement (§7.3).

### 7.3 Human ↔ AI agreement — `GET /api/analytics/agreement`
For jobs that have **both** a human vote (`winner_model`) and an AI verdict, computes the % where the two pick the same engine, per modality (image/TTS/video) and overall. AI winner precedence: video Creative-Director verdict → `ai_eval.winner_engine` → highest Core-5 `overall_score`.

### 7.4 Per-arena stats — `GET /api/{sxs,image,tts}/stats`
Win-rates and per-metric average scores for the arena leaderboards.

---

## 8. System architecture

### 8.1 Unified single-service model
One Docker image (multi-stage, root `Dockerfile`):
1. **Stage 1 (node:20-alpine):** `npm ci` + `npm run build` of the Next.js app with `NEXT_PUBLIC_API_URL=""` → static export in `frontend/out`.
2. **Stage 2 (python:3.12-slim):** install `backend/requirements.txt`, copy backend, copy `frontend/out` → `/app/static`. Run `uvicorn main:app` on `$PORT` (8080 in container).

FastAPI (`main.py`) serves **both** the JSON API and the compiled UI:
- All API routers are registered **before** the static catch-all `app.mount("/", StaticFiles(directory=static_dir, html=True))`, so `/api/*` always wins.
- A custom 404 handler returns JSON for `/api/*` misses and falls back to `index.html` for client-side routes (SPA behavior).
- Image and TTS routers are `include_router`'d near the bottom of `main.py`; video ("sxs") routes are defined inline in `main.py`.

```
                    ┌──────────────────── Cloud Run (genmedia-sxs-v2) ────────────────────┐
                    │  uvicorn :8080                                                       │
   Browser ───────▶ │  FastAPI (main.py)                                                   │
                    │   ├─ /api/*  → routers (sxs inline, image_routes, tts_routes)        │
                    │   └─ /*      → StaticFiles(next export)  [catch-all, registered last] │
                    └───────┬───────────────────┬────────────────────────┬────────────────┘
                            │                   │                        │
                     ┌──────▼──────┐   ┌────────▼─────────┐   ┌──────────▼──────────┐
                     │  Firestore   │   │  Cloud Storage   │   │ Model + judge APIs  │
                     │ jobs / votes │   │ (GCS media)      │   │ Vertex / FAL / etc. │
                     └─────────────┘   └──────────────────┘   └─────────────────────┘
```

### 8.2 Frontend
- **Next.js 16** (App Router), **React 19**, **Tailwind v4**, **Recharts** (analytics charts), **Recoil** (state), **papaparse** (CSV), **lucide-react** (icons).
- `next.config.ts` switches on `NODE_ENV`: production → `output: 'export'`, `trailingSlash: true`; development → rewrites `/proxy-api/api/:path*` to `BACKEND_URL` (default `http://localhost:8011`).
- `frontend/src/lib/api.ts`: `API_BASE_URL = NEXT_PUBLIC_API_URL ?? "/proxy-api"`. Admin token persisted in `localStorage` (`pp_admin_token`) and sent as `X-Admin-Token` via `adminFetch`.
- **TypeScript build errors are intentionally ignored** (`typescript.ignoreBuildErrors: true`) — `npm run lint` (eslint) is the only static check.

### 8.3 Backend
- **FastAPI + uvicorn**, Python 3.12.
- Async generation with concurrency caps via env (`*_CONCURRENCY`, `GEN_API_CONCURRENCY`) and `util/ratelimit.py`.
- Firestore via `google-cloud-firestore` / `firebase_admin`; GCS via `google-cloud-storage`; judges via `google-genai` (Vertex).

### 8.4 Generation → evaluation job flow
1. Admin uploads a cases JSON (`POST /api/{sxs,image,tts}/upload`, or `run-gcs` for a GCS-hosted cases file).
2. A Firestore job doc is created (status `generating`/`pending`).
3. The pipeline generates media for each side concurrently (`asyncio.gather`), tolerating per-side failure (a model error is stored as that side's result and processing continues).
4. Media is uploaded to GCS; `results.<engine>` is patched with `{status, url, latency…}`.
5. The AI judge runs (`run_auto_eval`), writing `ai_eval` / `auto_evals` / `director_eval`; failures set `auto_eval_status = error`.
6. Humans vote blind; analytics aggregate over jobs + votes.
- **Dedup / re-run semantics (video):** a case key `customer|prompt_id` is only skipped when status is `done` (both models produced video); `failed` and `in_progress` remain re-runnable so a missing API result can be retried.

---

## 9. Data model

### 9.1 Firestore — isolated collections per modality
- **Video:** `sxs_jobs` (+ `sxs_votes`, `sxs_runs`). Job docs are filtered by `source == "sxs_auto"`.
- **Image:** `image_jobs` (+ `image_votes`).
- **TTS:** `tts_jobs` (+ `tts_votes`).

**Job document (representative, video):**
```jsonc
{
  "id": "sxs_<caseid>_<ms>",
  "source": "sxs_auto",
  "batch_id": "…",
  "customer": "…",
  "prompt_id": "…",           // embeds customer name — mask in UI
  "prompt": "…",
  "ratio": "16:9",
  "modality": "t2v|i2v|r2v",
  "duration": 8,
  "reference_images": ["gs://…"],
  "reference_videos": ["gs://…"],
  "categories": ["…"],        // controlled taxonomy / auto-tagged
  "language": "…",            // TTS
  "mode": "t2i|i2i",          // image
  "timestamp": 1770000000.0,
  "results": {                // keyed by engine id
    "<engine>": { "status": "generating|success|error",
                  "url": "gs://…", "engine": "…",
                  "latency": 42.0,        // video: seconds
                  "latency_ms": 4200,     // image/tts: ms
                  "error": "…" }
  },
  "side_map": { "A": "<engineId>", "B": "<engineId>" },   // blind→identity
  "auto_eval_status": "pending|done|error",
  "ai_eval":   { "winner_side": "A|B|TIE", "winner_engine": "…",
                 "A": {…scores…}, "B": {…scores…}, "model": "…" },  // image/tts
  "auto_evals":   { "<engine>": { "overall_score": 4.2, … } },      // video Core-5
  "director_eval":{ "winner_model": "<engine>", "reasoning": "…" }   // video pairwise
}
```

**Vote document:**
```jsonc
{
  "id": "sxsvote_<ms>",
  "job_id": "…",
  "winner_side": "A|B|tie",
  "winner_model": "<engine>",
  "loser_model": "<engine>",
  "scores": { "<metric>": 1..5 },
  "justification": "…",
  "ldap": "<handle>",
  "timestamp": 1770000000.0
}
```

### 9.2 Cloud Storage (GCS)
- Bucket: `project-pulse` (env `GCS_BUCKET_NAME`, `OUTPUT_GCS_BUCKET`). Generated media + uploaded reference assets live here.
- Media is **never** exposed as raw `gs://` URLs to the client. It is served through the authenticated media proxy `GET /api/media?url=gs://…` (or short-lived signed URLs generated server-side at serve time).

### 9.3 Model registry — `backend/models.json`
Keyed by model id; each entry: `{ id, name, provider, model_id, type, is_active }`. `type` ∈ `t2v/i2v/r2v/t2i/i2i/tts…`. The admin API mutates the registry (add / toggle active / delete). Matchups (which models face off) are resolved in the pipelines.

---

## 10. API surface (selected)

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/api/admin/login` | POST | — | Exchange `ADMIN_USER`/`ADMIN_PASS` for a token. |
| `/api/models` | GET | — | List model registry. |
| `/api/models`, `/api/models/{id}/toggle`, `/api/models/{id}` | POST/POST/DELETE | admin | Manage registry. |
| `/api/{sxs,image,tts}/upload` | POST | admin | Upload cases JSON → generate + auto-judge. |
| `/api/sxs/run-gcs` | POST | admin | Launch a batch from a GCS-hosted cases file. |
| `/api/sxs/catalog` | GET | — | Counts by customer/modality for a GCS cases file (pre-launch filter). |
| `/api/{sxs,image,tts}/pair` | GET | — | Fetch a blind A/B pair for voting (filters: tag, prompt_id, search). |
| `/api/{sxs,image,tts}/vote` | POST | — | Record a blind human vote (20s dedup window). |
| `/api/{sxs,image,tts}/stats` | GET | — | Win-rates + per-metric scores. |
| `/api/sxs/jobs`, `/api/sxs/jobs/{id}` | GET | — | Job list / detail. |
| `/api/sxs/jobs/{id}/retry`, `/api/sxs/retry-failures`, `/api/sxs/resume` | POST | admin | Recover failed/partial generations. |
| `/api/sxs/aieval/{id}`, `/api/sxs/director-eval` | GET/POST | — /admin | AI-judge verdicts. |
| `/api/analytics/latency` | GET | — | Avg/p50 latency per model × modality. |
| `/api/benchmark/winmap` | GET | — | Segmented win-map with Wilson CIs. |
| `/api/analytics/agreement` | GET | — | Human vs AI-judge agreement. |
| `/api/leaderboard/users`, `/api/sxs/leaderboard/users` | GET | — | Top evaluators. |
| `/api/media` | GET | — | Authenticated media proxy for GCS assets. |
| `/api/slides/generate`, `/api/slides/append/{batch}` | POST | admin | Google Slides deck export. |
| `/slideware` | GET | — | HTML presentation view. |
| `/api/health` | GET | — | Liveness. |

Full reference: `docs/api/API_REFERENCE.md`, `docs/api/openapi.yaml`, `backend/README.md`.

---

## 11. Providers

Each pipeline dispatches to a provider module by the registry `provider` field (`backend/providers/`):
- **Video:** `vertex_provider.py` (Veo), `fal_provider.py` (Kling / Seedance / Grok via FAL), `omni_provider.py` (Omni).
- **Image:** `gemini_image_provider.py`, `gpt_image_provider.py`, `mai_image_provider.py`.
- **TTS:** `gemini_tts_provider.py`, `elevenlabs_provider.py` (native mode via `ELEVENLABS_USE_NATIVE`, model `ELEVENLABS_MODEL`, fallback `ELEVENLABS_FALLBACK_MODEL`).

External dependencies: Vertex AI (Veo + all Gemini judges/generators), FAL (Kling/Seedance/Grok), OpenAI (GPT-image-2), MAI-Image, ElevenLabs. Google Drive/Sheets integration (`util/drive_utils.py`, `util/sheets_utils.py`) supports batch ingestion and slide/report export.

---

## 12. Security & privacy

- **Blindness integrity:** identities hidden and A/B randomized at serve time; revealed only post-vote.
- **PID confidentiality:** prompt IDs embed customer/company names — UI must mask to last 4 chars; treat prompt datasets as confidential (not committed; provided locally / via GCS).
- **Admin auth:** token-based (`X-Admin-Token`), gating all mutating endpoints via `Depends(require_admin)`.
- **Secrets:** provider keys and admin password are **not committed**. Local: `backend/.env` + `backend/private.key`. Cloud Run: env vars + Secret Manager (`FAL_KEY`, `ADMIN_PASS`, `ELEVENLABS_API_KEY`).
- **Media access:** GCS assets are served only via the authenticated proxy / signed URLs; no public raw `gs://` exposure.
- **Vote integrity:** 20-second per-(ldap, job) idempotency window; anonymous/global handles excluded from the leaderboard.

---

## 13. Non-functional requirements

- **Deployment target:** Cloud Run service `genmedia-sxs-v2`, project `vital-octagon-19612`, region `us-central1`. Runtime SA `claude@vital-octagon-19612.iam.gserviceaccount.com`.
- **Runtime sizing:** 4Gi memory, 4 vCPU, request timeout 3600s (long video generation), concurrency 20, `--no-cpu-throttling`, `--min-instances 1` (warm), `--allow-unauthenticated`.
- **Resilience:** per-side generation failures are isolated (job continues, side marked `error`, retryable); judge failures never block serving; retry-with-exponential-backoff around Vertex judge calls (4 attempts, 6s initial).
- **Statistical rigor:** win-rates always reported with 95% Wilson CIs; segments below `min_n` suppressed.
- **Latency normalization:** all latency surfaced in seconds regardless of per-modality storage unit.
- **Scalability:** async generation with configurable concurrency caps; analytics computed by streaming Firestore collections (acceptable at current internal scale; see §16).

---

## 14. Configuration (environment variables)

**Core:** `GCP_PROJECT_ID`, `GCS_BUCKET_NAME` / `OUTPUT_GCS_BUCKET`, `ADMIN_USER`, `ADMIN_PASS`.
**Collections:** `SXS_COLLECTION`, `SXS_VOTES_COLLECTION`, `SXS_RUNS_COLLECTION`, `IMAGE_COLLECTION`, `IMAGE_VOTES_COLLECTION`, `TTS_COLLECTION`, `TTS_VOTES_COLLECTION`.
**Judge / eval:** `EVAL_PROJECT`, `EVAL_LOCATION`, `EVAL_MODEL`, `IMAGE_EVAL_PROJECT`, `IMAGE_EVAL_MODEL`, `IMAGE_LOCATION`, `TTS_EVAL_PROJECT`, `TTS_EVAL_MODEL`, `LANG_TAGGER_MODEL`.
**Providers:** `FAL_KEY`, `ELEVENLABS_API_KEY`, `ELEVENLABS_MODEL`, `ELEVENLABS_FALLBACK_MODEL`, `ELEVENLABS_USE_NATIVE`, `GEMINI_TTS_MODEL`, `GPT_IMAGE_MODEL`/`GPT_IMAGE_T`/`GPT_IMAGE_I`, `MAI_IMAGE_MODEL`/`MAI_T`/`MAI_I`, `OMNI_PROJECT`/`OMNI_LOCATION`/`OMNI_MODEL_ID`/`OMNI_API_REVISION`.
**Concurrency:** `GEN_API_CONCURRENCY`, `IMAGE_CONCURRENCY`, `TTS_CONCURRENCY`.
**Integrations:** `DRIVE_IMPERSONATE_USER`.

---

## 15. Local development & operations

```bash
# Backend (serves API on :8011, reads backend/.env; expects backend/venv)
cd project-pulse && ./restart_local.sh
# Frontend dev (proxies /proxy-api/api/* → :8011)
cd project-pulse/frontend && npm run dev
# Lint (only static check)
cd project-pulse/frontend && npm run lint
# Production build (static export served by backend)
cd project-pulse/frontend && npm ci && npm run build
# Deploy
cd project-pulse && ./deploy_v2.sh
```

**Batch ingestion helpers** (`backend/*.py`): `run_anime_batch.py`, `load_v2v_bench.py`, `resume_batch.py`, `reeval_all.py`, `retag_*` scripts, `build_*` case builders. Sample case files: `backend/*_cases*.json`, `image_cases.sample.json`, `tts_cases.sample.json`.

---

## 16. Open issues / future work

- **No automated tests / CI.** `npm run lint` is the only gate; TS build errors are suppressed. Add pipeline/evaluator/analytics unit tests.
- **Analytics scans full collections** per request (win-map, agreement, latency stream every job). Fine at internal scale; will need pre-aggregation / caching / BigQuery rollups as data grows (`google-cloud-bigquery` is already a dependency).
- **Video matchup is currently fixed** to Seedance-vs-Omni in the auto pipeline, while the registry supports many models — unify the multi-model admin flow with the arena.
- **Human votes are sparse**, so the win-map relies on the AI judge; expand human coverage and continuously monitor the agreement metric to validate the judge.
- **Repo hygiene:** `project-pulse/` is not under version control in this checkout; `archive/` holds dead code kept only for reference.
```
