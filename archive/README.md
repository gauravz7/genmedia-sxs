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

## Kept in place (still required)
Runtime: `main.py`, `sxs_pipeline.py`, `image_pipeline.py`, `tts_pipeline.py`,
`image_routes.py`, `tts_routes.py`, `video_evaluator_sdk.py`, `image_evaluator.py`,
`tts_evaluator.py`, `providers/`, `util/`, `models.json`, `requirements.txt`,
`Dockerfile`, `Procfile`, `.env`.
Current tooling: `resume_batch.py`, `retag_video.py`, `deploy_v2.sh`, `restart_local.sh`.
Format references: `*.sample.json`. Docs: `README.md`, `EVAL_GUIDE.md`, `docs/`.
