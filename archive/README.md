# Archive

Code and artifacts no longer required by the running app (Project Pulse / GenMedia SxS v2).
Nothing here is imported by `backend/main.py`, the pipelines, routes, providers, or `util/`,
and the runtime modules were confirmed to compile after these were moved out.

`archive/` is listed in `.gcloudignore`, so none of this ships to Cloud Run on `deploy_v2.sh`.
Files were moved (not deleted) and can be restored with `git mv` / `mv` if needed.

## What's here

### backend/tests/  (16 files)
Ad-hoc dev test scripts — provider probes, speed tests, SDK spikes
(`test_*.py`). Not a pytest suite; one-off manual checks.

### backend/scripts/  (20 files)
One-off operational / setup / reporting scripts that aren't part of the request flow:
- **Firestore maintenance:** `deep_scrub_firestore.py`, `scrub_firestore_urls.py`,
  `wipe_history.py`, `delete_jobs.py`, `fix_jobs.py`, `migrate_to_firestore.py`,
  `inject_i2v_job.py`, `show_db.py`
- **Google Sheets flow (removed from the UI):** `add_sheet_dropdown.py`,
  `check_columns.py`, `create_test_sheet.py`
- **Slideware / reporting:** `generate_google_slides.py`, `generate_pptx.py`,
  `generate_slideware.py`, `slideware.html`
- **One-off uploads / setup:** `bulk_drive_upload.py`, `upload_hippo_assets.py`,
  `setup_elevenlabs_voices.py`
- **Verification spikes:** `verify_generation.py`, `verify_signing_v2.py`

### backend/data/  (4 files)
Stale local data dumps / logs — not read at runtime (the app uses Firestore):
`backend.logs`, `eval_jobs.json`, `votes.json`, `prompts.json`.

### backend/static_stale/
An old Next.js build that used to be committed under `backend/static/`. The unified
`Dockerfile` runs `rm -rf /app/static` and copies a fresh frontend build, so this
checked-in copy is never served.

### root/  (8 files)
- Stale process-id files: `backend.pid`, `frontend.pid`
- Test artifacts: `test_batch.csv`, `test_url.py`, `done_cases.json`
- Superseded deploy scripts (current one is `deploy_v2.sh`):
  `deploy_cloudrun.sh`, `deploy_unified.sh`, `deploy_sxs.sh`

### v3/
The abandoned execution-centric rewrite — its own FastAPI app, pytest suite and
Next.js frontend. The refactor was rejected; v2 is the version being developed.
Kept for reference only; nothing in it is imported by v2. (`node_modules/` and
`.next/` inside it are gitignored build caches — delete them freely.)

### docs/  (2 files)
`REFACTOR_PLAN.md` and `TECHNICAL_PRD.md` — both describe the rejected v3
direction. Background reading, not a roadmap.

### backend/scripts/  — second wave (6 files)
Customer- or batch-specific one-offs, superseded or already run:
- `load_v2v_bench.py` — generalized by the intake API (`POST /api/sxs/outputs`)
- `delete_mihoyo_jobs.py`, `run_anime_batch.py`, `retag_and_eval_v2v.py` — single-batch jobs
- `build_gaming_concept_cases.py`, `build_tts_synthetic.py` — dataset builders for batches already loaded

### backend/data/  — second wave
`mihoyo_jobs_backup_1782975062.json`, a stale pre-migration Firestore dump.

## Kept in place (still required)
Runtime, after `main.py` was decomposed (see its module map): `main.py` (app
assembly only), `config.py`, `registry.py`, `store.py`, `auth.py`, `tagging.py`,
`generation.py`, the routers (`models_routes.py`, `admin_routes.py`,
`video_routes.py`, `image_routes.py`, `tts_routes.py`, `intake_routes.py`,
`analytics_routes.py`, `media_routes.py`, `slides_routes.py`,
`legacy_routes.py`), the pipelines and evaluators, `intake.py`,
`model_resolver.py`, `providers/`, `util/`, `tests/`, `models_builtin.json`,
`models.json`, `requirements.txt`, `Dockerfile`, `Procfile`, `.env`.
Current tooling: `resume_batch.py`, `reeval_all.py`, `retag_{image,tts,video}.py`,
`deploy_v2.sh`, `restart_local.sh`.
Format references: `*.sample.json`, the `*_cases.json` datasets (gitignored —
they embed customer names). Docs: `README.md`, `EVAL_GUIDE.md`, `docs/`.
