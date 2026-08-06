# Backend module reference

What each backend module owns, and every endpoint it serves. `main.py` used to hold
all of this inline (~2,950 lines); it is now application assembly only and each
concern lives in its own module beside the pre-existing modality routers.

Companion docs: [`API_REFERENCE.md`](API_REFERENCE.md) (request/response detail),
[`DATA_INTAKE.md`](DATA_INTAKE.md) (the customer-facing intake contract),
[`../../backend/README.md`](../../backend/README.md) (data model + full API).

**Legend:** 🔒 = `Depends(require_admin)` (send `X-Admin-Token`).

---

## Assembly and shared modules

### `main.py` — application assembly
Creates the `FastAPI` app, installs the `RequestValidationError` handler and CORS,
then `include_router`s every router **before** mounting the Next.js static export at
`/`, so `/api/*` always beats the catch-all. A 404 handler falls back to `index.html`
for client-side routes.

It also re-exports `registry`, `PROVIDER_TRANSPORT`, `RegisteredModel` and
`require_admin`, because `model_resolver.py`, `tts_pipeline.py` and
`tests/conftest.py` reach for them as `main.<name>`. Keep those names importable
from `main`.

### `config.py` — environment
`GCP_PROJECT_ID`, `GCS_BUCKET_NAME`, `SXS_COLLECTION` / `SXS_VOTES_COLLECTION` /
`SXS_RUNS_COLLECTION`, `VALID_RATIOS`, and `normalize_gcs_url()` (strips signed-URL
query params and `/api/media?url=` wrappers back to a canonical GCS URL). Also pops
`GOOGLE_APPLICATION_CREDENTIALS` so Application Default Credentials always win.

### `registry.py` — the model registry
One registry across all three modalities. `RegisteredModel` (id, `provider`,
`model_id`, `type`, `is_active`, optional `quality`, derived `transport`) and
`RegistryManager`, which merges the committed `models_builtin.json` seed with the
gitignored `models.json` admin overlay. `PROVIDER_TRANSPORT` enforces the platform
rule — **every Google model runs on Vertex AI, every non-Google model through FAL** —
and an unknown provider is rejected on write. `provider` stays the dispatch key the
pipelines switch on; don't collapse it to two values.

### `store.py` — legacy Firestore documents
`Job`/`JobsManager`, `Vote`/`VotesManager`, `Prompt`/`PromptsManager` over the
pre-SxS `eval_jobs` / `votes` / `prompts` collections, plus their singletons. The
three modality pipelines talk to Firestore directly and do **not** go through these.

### `auth.py` — admin authentication
A stateless token: `sha256("project-pulse-sxs:v1:{ADMIN_USER}:{ADMIN_PASS}")`.
`require_admin` is the FastAPI dependency that gates mutating/expensive endpoints.
`image_routes`, `tts_routes` and `intake_routes` each mirror this rather than
importing it, so a modality router stays independently importable — the token is
identical, so one login works everywhere.

### `tagging.py` / `generation.py` — background workers
`tagging.py` runs Gemini auto-tagging over a job or a prompt as a background task.
`generation.py` holds `PromptRequest` and `_run_generation_background`, the legacy
multi-model video generation engine driving `/api/generate` and the admin retry
endpoint. Both are shared by more than one router, which is why they aren't folded
into either one.

---

## Routers

### `models_routes.py` — the registry API
Registering a model here is what makes its name usable in the intake API and in the
compose forms.

| | Method | Path | Purpose |
|---|---|---|---|
| | `GET` | `/api/models` | All registered models; `?modality=video\|image\|tts` filters by `type`. |
| 🔒 | `POST` | `/api/models` | Add or update a model. Validates `provider` → `transport`. |
| 🔒 | `POST` | `/api/models/{model_id}/toggle` | Flip `is_active`. Inactive models are rejected by the intake gate. |
| 🔒 | `DELETE` | `/api/models/{model_id}` | Deleting a **builtin** deactivates it — a true delete would return on restart. |

### `admin_routes.py` — login, prompts, tags, Sheets, legacy jobs view
| | Method | Path | Purpose |
|---|---|---|---|
| | `POST` | `/api/admin/login` | Exchange `ADMIN_USER`/`ADMIN_PASS` for the admin token. |
| | `GET` | `/api/admin/prompts` | List saved prompts. |
| 🔒 | `POST` | `/api/admin/prompts` | Save a prompt; queues Gemini auto-tagging in the background. |
| 🔒 | `DELETE` | `/api/admin/prompts/{prompt_id}` | Delete a saved prompt. |
| 🔒 | `POST` | `/api/admin/generate-tags` | Ad-hoc: tag arbitrary text with Gemini. |
| | `GET` | `/api/tags` | Every distinct tag across jobs and prompts, for the search/filter UI. |
| 🔒 | `POST` | `/api/admin/backfill-tags` | Auto-tag every job and prompt that has no categories. |
| 🔒 | `POST` | `/api/admin/batch/sheet/load` | Load a batch of cases from a Google Sheet. |
| 🔒 | `POST` | `/api/admin/batch/sheet/update` | Write results back to the sheet. |
| | `GET` | `/api/admin/jobs` | The legacy (`eval_jobs`) admin jobs list. **Note: not admin-gated** — a pre-existing gap, read-only. |
| 🔒 | `DELETE` | `/api/admin/jobs/{job_id}` | Delete a legacy job. |
| 🔒 | `POST` | `/api/admin/jobs/{job_id}/retry` | Re-run the failed models of a job; `include_stuck=true` also retries ones wedged in `generating`. |
| | `GET` | `/api/admin/jobs/{job_id}/status` | Per-model generation status for one job. |

### `video_routes.py` — the video (`sxs`) modality
The live video path. Isolated collections (`sxs_jobs`, `sxs_votes`, `sxs_runs`),
mirroring how `image_routes` and `tts_routes` own their modalities. Video duels are
**N-way**: `results` is keyed by model id.

| | Method | Path | Purpose |
|---|---|---|---|
| 🔒 | `POST` | `/api/sxs/upload` | Upload a cases JSON + local asset files; one job per case, generated in the background. |
| | `GET` | `/api/sxs/jobs` | List jobs (optionally by batch), media URLs signed for the browser. |
| | `GET` | `/api/sxs/jobs/{job_id}` | One job. |
| 🔒 | `DELETE` | `/api/sxs/jobs/{job_id}` | Delete a pair. |
| 🔒 | `POST` | `/api/sxs/jobs/{job_id}/retry` | Re-generate failed side(s), then re-run the judge. |
| | `GET` | `/api/sxs/aieval/{job_id}` | The Core-5 auto-eval report — revealed to the voter only after they vote. |
| | `GET` | `/api/sxs/report.{json,csv}` | Batch export. |
| | `GET` | `/api/sxs/pair` | A random **blind** pair for the arena. |
| | `POST` | `/api/sxs/vote` | Store a human vote in `sxs_votes`. |
| | `GET` | `/api/sxs/catalog` | Counts by customer and modality for a GCS cases JSON, for the upload UI. |
| 🔒 | `POST` | `/api/sxs/retry-failures` | Retry every case where a provider returned nothing. |
| 🔒 | `POST` | `/api/sxs/resume` | Reprocess every pair that isn't fully complete — restart-safe batch continuation. |
| 🔒 | `POST` | `/api/sxs/director-eval` | Run the pairwise Creative-Director critique over completed pairs. |
| 🔒 | `POST` | `/api/sxs/cleanup-orphans` | Delete jobs that never reached `auto_eval_status: done`. |
| | `GET` | `/api/sxs/runs` | Run log: every batch launched, with done/remaining counts. |
| | `GET` | `/api/sxs/failures` | Cases where a provider produced no result. |
| 🔒 | `POST` | `/api/sxs/run-gcs` | Load cases straight from a GCS JSON (references already `gs://`). |
| 🔒 | `POST` | `/api/admin/generate-json` | Admin variant of `upload` — cases JSON plus optional asset files. |
| 🔒 | `POST` | `/api/sxs/compose` | Run one case from the compose-box form. |
| | `POST` | `/api/sxs/translate` | Translate a prompt to English with Gemini 2.5 Flash. |

### `image_routes.py` — the image modality
Image duels are structurally **two-sided**: `results` is keyed `"A"`/`"B"` with a
`side_map` (and `side_specs`) recording which model is which, so the arena stays blind.

| | Method | Path | Purpose |
|---|---|---|---|
| | `GET` | `/api/image/matchups` | The preset matchups the compose/upload UI offers. |
| 🔒 | `POST` | `/api/image/upload` | Cases JSON + optional local input images; one job per case. |
| 🔒 | `POST` | `/api/image/compose` | Run one case from the compose form. |
| | `GET` | `/api/image/jobs`, `/api/image/jobs/{job_id}` | List / fetch jobs. |
| 🔒 | `DELETE` | `/api/image/jobs/{job_id}` | Delete a job. |
| 🔒 | `POST` | `/api/image/jobs/{job_id}/retry` | Re-generate a failed side (prefers `side_specs` over the preset matchup). |
| | `GET` | `/api/image/aieval/{job_id}` | Judge result — revealed after the human vote. |
| | `GET` | `/api/image/pair` | A random blind A/B pair where both sides succeeded. |
| | `GET` | `/api/image/tags` | Distinct categories, for the arena tag filter. |
| | `POST` | `/api/image/vote` | Store a blind vote; resolves winner/loser through `side_map`. |
| | `GET` | `/api/image/stats`, `/api/image/leaderboard` | Win rates, per-metric averages, per-matchup breakdown (`leaderboard` is an alias). |
| | `GET` | `/api/image/leaderboard/users` | Voter leaderboard for this modality. |
| | `GET` | `/api/image/report.{json,csv}` | Export. |
| | `GET` | `/api/image/media` | Modality-local media proxy. |

### `tts_routes.py` — the TTS modality
`APIRouter(prefix="/api/tts")`, so the paths below are relative to that. Two-sided
like image (`results` keyed `"A"`/`"B"` + `side_map`).

| | Method | Path | Purpose |
|---|---|---|---|
| 🔒 | `POST` | `/upload` | Cases JSON; one job per case, generated in the background. |
| 🔒 | `POST` | `/compose` | Run one case from the compose form. |
| | `GET` | `/jobs`, `/jobs/{job_id}` | List / fetch jobs. |
| 🔒 | `DELETE` | `/jobs/{job_id}` | Delete a job. |
| 🔒 | `POST` | `/jobs/{job_id}/retry` | Re-generate a failed side. |
| | `GET` | `/aieval/{job_id}` | The audio judge's result — revealed after the human vote. |
| | `GET` | `/pair` | A random blind A/B pair. |
| | `POST` | `/vote` | Store a blind vote; resolves winner/loser engine via `side_map`. |
| | `GET` | `/tags`, `/languages` | Filter facets actually present in the data. |
| | `GET` | `/stats`, `/leaderboard` | Engine win rates and per-metric averages. |
| | `GET` | `/leaderboard/users` | Voter leaderboard for this modality. |
| | `GET` | `/voices` | Voices for the compose form (the 30 prebuilt Gemini voices + the curated ElevenLabs set). |
| | `GET` | `/report.{json,csv}` | Export. |
| | `GET` | `/media` | Modality-local media proxy. |

### `intake_routes.py` — the standard data-intake contract
Six admin-gated endpoints, all returning the same partial-success envelope
(`{status, batch_id, job_ids, count, skipped[]}`) so one bad row is reported rather
than aborting the batch. Model names are validated against the registry via
`model_resolver`. Ingested docs carry `source: "sxs_auto"` — without it every
list/pair endpoint filters them out. Full contract in [`DATA_INTAKE.md`](DATA_INTAKE.md).

| | Method | Path | Purpose |
|---|---|---|---|
| | `GET` | `/api/intake/models` | The model names each modality accepts. Unauthenticated. |
| 🔒 | `POST` | `/api/sxs/prompts` | Run video cases on explicitly named models. N-way. |
| 🔒 | `POST` | `/api/image/prompts` | Run image cases on a named pair of models (exactly 2). |
| 🔒 | `POST` | `/api/tts/prompts` | Run TTS cases on a named pair of engines (exactly 2). |
| 🔒 | `POST` | `/api/sxs/outputs` | Register customer-generated video (BYOO). `outputs` keyed by model id. |
| 🔒 | `POST` | `/api/image/outputs` | Register customer-generated images. Exactly 2 outputs per case. |
| 🔒 | `POST` | `/api/tts/outputs` | Register customer-generated audio. Exactly 2 outputs per case. |

`intake.py` does the work behind `outputs`: it rehosts every URL (outputs *and*
reference assets) into our bucket, deriving the content type — do **not** use
`gcs_utils.upload_from_url` for video/audio, which hardcodes `image/png` for
`gs://`→GCS transfers.

### `analytics_routes.py` — stats, leaderboards, cross-modality analytics
The one place that is deliberately **not** modality-isolated: it reads every
modality's collections.

| | Method | Path | Purpose |
|---|---|---|---|
| | `GET` | `/api/evaluation/stats` | Legacy win rates / leaderboard; filterable by tag and ldap. |
| | `GET` | `/api/sxs/stats` | Video win rates over `sxs_votes` + `sxs_jobs`. |
| | `GET` | `/api/sxs/tags` | Distinct categories across video jobs, for the arena filter. |
| | `GET` | `/api/sxs/leaderboard/users`, `/api/leaderboard/users` | Per-modality and legacy voter leaderboards. |
| | `GET` | `/api/analytics/latency` | Average generation latency per (modality, model). |
| | `GET` | `/api/benchmark/winmap` | Where Google models win — AI-judge verdicts aggregated across all three modalities, with Wilson confidence intervals. |
| | `GET` | `/api/analytics/agreement` | How often the AI judge agrees with human blind votes, per modality. |
| | `GET` | `/api/votes/count` | Total votes one ldap has cast across all modalities. |
| | `GET` | `/api/leaderboard`, `/api/votes/leaderboard` | Top voters overall and per modality. |

### `media_routes.py` — health and the media proxy
| | Method | Path | Purpose |
|---|---|---|---|
| | `GET` | `/api/health` | Liveness probe. |
| | `GET` | `/api/media` | Authenticated GCS proxy with HTTP range support (video seeking). |

**Raw `gs://` URLs are never handed to the browser** — everything goes through
`/api/media`, which is also the SSRF choke point.

### `slides_routes.py` — decks and slideware
| | Method | Path | Purpose |
|---|---|---|---|
| 🔒 | `POST` | `/api/slides/generate` | Build a Google Slides deck with Drive-embedded videos. |
| 🔒 | `POST` | `/api/slides/append/{batch_name}` | Append one batch to the existing deck. |
| | `GET` | `/slideware` | Serve the generated HTML slideware. |
| 🔒 | `POST` | `/api/slideware/regenerate` | Rebuild that HTML from current Firestore data. |
| 🔒 | `POST` | `/api/slideware/pptx` | Generate a PPTX with embedded videos for given batches. |
| | `GET` | `/api/slideware/pptx/download` | Download the most recent PPTX. |
| | `GET` | `/api/slideware/feedback` | Best picks + comments. |
| 🔒 | `POST` | `/api/slideware/feedback/{pick,comment}` | Record a best-video pick / a comment for a batch+tier. |

### `legacy_routes.py` — pre-multi-modality endpoints
From the flow that predates the three-modality split. **No longer called by the
frontend — don't extend these.** The live paths are `/api/{sxs,image,tts}/*`.

| | Method | Path | Superseded by |
|---|---|---|---|
| 🔒 | `POST` | `/api/generate` | `/api/sxs/{upload,compose,prompts}` |
| 🔒 | `POST` | `/api/generate-image` | `/api/image/{upload,compose,prompts}` |
| 🔒 | `POST` | `/api/upload` | the per-modality upload endpoints |
| | `GET` | `/api/evaluation/pair` | `/api/{sxs,image,tts}/pair` |
| | `POST` | `/api/evaluation/vote` | `/api/{sxs,image,tts}/vote` |
| 🔒 | `POST` | `/api/admin/votes/prune` | — (still a usable maintenance endpoint) |

---

## Non-router backend modules

| module | role |
|---|---|
| `sxs_pipeline.py` / `image_pipeline.py` / `tts_pipeline.py` | Per-modality job creation and generation, concurrency-limited by `*_CONCURRENCY`. |
| `video_evaluator_sdk.py` / `image_evaluator.py` / `tts_evaluator.py` | The LLM-as-judge for each modality (multimodal Gemini on Vertex AI). |
| `image_taxonomy.py` | Category classification for image jobs. |
| `intake.py` | Rehosting + job-doc writing behind the `outputs` endpoints. |
| `model_resolver.py` | The shared "is this model registered and active" gate. Imports `main` lazily inside its functions — a module-level import would be circular. |
| `providers/` | One module per generation backend; pipelines dispatch on the registry's `provider` field. |
| `util/` | `gcs_utils.py` (storage), `asset_intake.py` (reference-media ingestion), `drive_utils.py` + `sheets_utils.py`, `ratelimit.py` (≤3 concurrent generative calls process-wide, with 429 backoff). |
| `retag_{image,tts,video}.py`, `reeval_all.py`, `resume_batch.py` | Operational scripts, run manually against real Firestore/GCS. |
