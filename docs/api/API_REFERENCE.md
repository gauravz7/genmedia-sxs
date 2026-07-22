# Project Pulse — API Reference

OpenAPI **3.1.0** · 101 operations · 96 paths.

- Production: `https://genmedia-sxs-v2-440790012685.us-central1.run.app` (Google-IAM gated)
- Local: `http://localhost:8011` · interactive docs at `/docs`, spec at `/openapi.json`
- Admin endpoints require header `X-Admin-Token: sha256('project-pulse-sxs:v1:admin:<ADMIN_PASS>')`

## System
_Health and service metadata._

| Method | Path | Summary |
|--------|------|---------|
| `GET` | `/api/health` | Health Check |

## Video SxS
_Blind side-by-side video evaluation — pairs, votes, stats, catalog, generation._

| Method | Path | Summary |
|--------|------|---------|
| `GET` | `/api/evaluation/pair` | Get Random Eval Pair |
| `GET` | `/api/evaluation/stats` | Get Stats |
| `POST` | `/api/evaluation/vote` | Cast Vote |
| `GET` | `/api/sxs/aieval/{job_id}` | Sxs Get Aieval |
| `GET` | `/api/sxs/catalog` | Sxs Catalog |
| `POST` | `/api/sxs/cleanup-orphans` | Sxs Cleanup Orphans |
| `POST` | `/api/sxs/compose` | Sxs Compose |
| `POST` | `/api/sxs/director-eval` | Sxs Director Eval |
| `GET` | `/api/sxs/failures` | Sxs Failures |
| `GET` | `/api/sxs/jobs` | Sxs List Jobs |
| `DELETE` | `/api/sxs/jobs/{job_id}` | Sxs Delete Job |
| `GET` | `/api/sxs/jobs/{job_id}` | Sxs Get Job |
| `POST` | `/api/sxs/jobs/{job_id}/retry` | Sxs Retry Job |
| `GET` | `/api/sxs/leaderboard/users` | Sxs User Leaderboard |
| `GET` | `/api/sxs/pair` | Sxs Pair |
| `GET` | `/api/sxs/report.csv` | Sxs Report Csv |
| `GET` | `/api/sxs/report.json` | Sxs Report Json |
| `POST` | `/api/sxs/resume` | Sxs Resume |
| `POST` | `/api/sxs/retry-failures` | Sxs Retry Failures |
| `POST` | `/api/sxs/run-gcs` | Sxs Run Gcs |
| `GET` | `/api/sxs/runs` | Sxs Runs |
| `GET` | `/api/sxs/stats` | Sxs Stats |
| `GET` | `/api/sxs/tags` | Sxs Tags |
| `POST` | `/api/sxs/translate` | Sxs Translate |
| `POST` | `/api/sxs/upload` | Sxs Upload |
| `POST` | `/api/sxs/vote` | Sxs Vote |

## Image SxS
_Image (T2I / I2I) side-by-side — pairs, votes, matchups, results, generation._

| Method | Path | Summary |
|--------|------|---------|
| `GET` | `/api/image/aieval/{job_id}` | Image Get Aieval |
| `POST` | `/api/image/compose` | Image Compose |
| `GET` | `/api/image/jobs` | Image List Jobs |
| `DELETE` | `/api/image/jobs/{job_id}` | Image Delete Job |
| `GET` | `/api/image/jobs/{job_id}` | Image Get Job |
| `POST` | `/api/image/jobs/{job_id}/retry` | Image Retry Job |
| `GET` | `/api/image/leaderboard` | Image Leaderboard |
| `GET` | `/api/image/leaderboard/users` | Image User Leaderboard |
| `GET` | `/api/image/matchups` | Image Matchups |
| `GET` | `/api/image/media` | Image Media Proxy |
| `GET` | `/api/image/pair` | Image Pair |
| `GET` | `/api/image/report.csv` | Image Report Csv |
| `GET` | `/api/image/report.json` | Image Report Json |
| `GET` | `/api/image/stats` | Image Stats |
| `GET` | `/api/image/tags` | Image Tags |
| `POST` | `/api/image/upload` | Image Upload |
| `POST` | `/api/image/vote` | Image Vote |

## TTS SxS
_Text-to-speech side-by-side (Gemini TTS vs ElevenLabs) — voices, pairs, votes, results._

| Method | Path | Summary |
|--------|------|---------|
| `GET` | `/api/tts/aieval/{job_id}` | Tts Get Aieval |
| `POST` | `/api/tts/compose` | Tts Compose |
| `GET` | `/api/tts/jobs` | Tts List Jobs |
| `DELETE` | `/api/tts/jobs/{job_id}` | Tts Delete Job |
| `GET` | `/api/tts/jobs/{job_id}` | Tts Get Job |
| `POST` | `/api/tts/jobs/{job_id}/retry` | Tts Retry Job |
| `GET` | `/api/tts/languages` | Tts Languages |
| `GET` | `/api/tts/leaderboard` | Tts Leaderboard |
| `GET` | `/api/tts/leaderboard/users` | Tts User Leaderboard |
| `GET` | `/api/tts/media` | Tts Media Proxy |
| `GET` | `/api/tts/pair` | Tts Pair |
| `GET` | `/api/tts/report.csv` | Tts Report Csv |
| `GET` | `/api/tts/report.json` | Tts Report Json |
| `GET` | `/api/tts/stats` | Tts Stats |
| `GET` | `/api/tts/tags` | Tts Tags |
| `POST` | `/api/tts/upload` | Tts Upload |
| `GET` | `/api/tts/voices` | Tts Voices |
| `POST` | `/api/tts/vote` | Tts Vote |

## Analytics
_Aggregated win rates, dimension analytics and latency._

| Method | Path | Summary |
|--------|------|---------|
| `GET` | `/api/analytics/agreement` | Analytics Agreement |
| `GET` | `/api/analytics/latency` | Analytics Latency |

## Leaderboard & Votes
_Evaluator leaderboards and vote counters._

| Method | Path | Summary |
|--------|------|---------|
| `GET` | `/api/leaderboard` | Full Leaderboard |
| `GET` | `/api/leaderboard/users` | Get User Leaderboard |
| `GET` | `/api/votes/count` | Votes Count |
| `GET` | `/api/votes/leaderboard` | Votes Leaderboard |

## Models
_Model registry — list, add, toggle active models._

| Method | Path | Summary |
|--------|------|---------|
| `GET` | `/api/models` | Get Models |
| `POST` | `/api/models` | Add Model |
| `DELETE` | `/api/models/{model_id}` | Delete Model |
| `POST` | `/api/models/{model_id}/toggle` | Toggle Model |

## Generation & Media
_Generation triggers and media proxy/serving helpers._

| Method | Path | Summary |
|--------|------|---------|
| `GET` | `/api/benchmark/winmap` | Benchmark Winmap |
| `POST` | `/api/generate` | Generate Videos |
| `POST` | `/api/generate-image` | Generate Image Api |
| `GET` | `/api/media` | Get Media Proxy |
| `GET` | `/api/tags` | Get All Tags |
| `POST` | `/api/upload` | Upload File Api |

## Admin
_Admin-only: prompts, batch import, generation, tagging, vote hygiene. Requires the X-Admin-Token header._

| Method | Path | Summary |
|--------|------|---------|
| `POST` | `/api/admin/backfill-tags` | Backfill Tags |
| `POST` | `/api/admin/batch/sheet/load` | Load Batch Sheet |
| `POST` | `/api/admin/batch/sheet/update` | Update Batch Sheet |
| `POST` | `/api/admin/generate-json` | Admin Generate Json |
| `POST` | `/api/admin/generate-tags` | Generate Tags Endpoint |
| `GET` | `/api/admin/jobs` | Get Admin Jobs |
| `DELETE` | `/api/admin/jobs/{job_id}` | Delete Job |
| `POST` | `/api/admin/jobs/{job_id}/retry` | Retry Failed Models |
| `GET` | `/api/admin/jobs/{job_id}/status` | Get Job Status |
| `POST` | `/api/admin/login` | Admin Login |
| `GET` | `/api/admin/prompts` | Get Admin Prompts |
| `POST` | `/api/admin/prompts` | Add Admin Prompt |
| `DELETE` | `/api/admin/prompts/{prompt_id}` | Delete Admin Prompt |
| `POST` | `/api/admin/votes/prune` | Prune Votes |

## Slideware
_Slide/feedback generation utilities._

| Method | Path | Summary |
|--------|------|---------|
| `POST` | `/api/slides/append/{batch_name}` | Append Slides For Batch |
| `POST` | `/api/slides/generate` | Generate Slides |
| `GET` | `/api/slideware/feedback` | Get Slideware Feedback |
| `POST` | `/api/slideware/feedback/comment` | Add Comment |
| `POST` | `/api/slideware/feedback/pick` | Set Best Video |
| `POST` | `/api/slideware/pptx` | Generate Pptx Endpoint |
| `GET` | `/api/slideware/pptx/download` | Download Existing Pptx |
| `POST` | `/api/slideware/regenerate` | Regenerate Slideware |
| `GET` | `/slideware` | Serve Slideware |
