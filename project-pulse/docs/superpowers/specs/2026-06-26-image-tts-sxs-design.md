# GenMedia SxS — Image & TTS Modalities (Design Spec)

**Date:** 2026-06-26
**Author:** Gaurav + Claude
**Status:** Draft for review

## 1. Goal

Extend the existing **GenMedia SxS** side-by-side benchmarking platform (currently
video-only: Veo / Kling / Seedance) with two new comparison **modalities**, built into
a *sibling copy* of the project so the original stays untouched:

1. **Image SxS** — Text-to-Image (T2I) and Image-edit (I2I), Gemini image models vs
   GPT-image (GPT2) on FAL, driven by a JSON cases upload, evaluated with blind human
   SxS **and** an AI judge.
2. **TTS SxS** — Gemini 3.1 Flash TTS (full director-style controls) vs ElevenLabs TTS,
   blind human audio A/B **and** AI judge.

Both reuse the existing SxS engine: cases-JSON upload → one job per case → background
two-model generation → store in Firestore/GCS → AI auto-judge → blind pairwise voting →
leaderboard + report.

## 2. Copy & layout

- Copy `~/Antigravity/SxS/project-pulse` → **`~/Antigravity/SxS-genmedia-v2/project-pulse`**.
- Exclude when copying: `node_modules/`, `backend/venv/`, `backend/venv.bak/`,
  `frontend/.next/`, `frontend/out/`, `*.log`, `__pycache__/`, `.git/`, large `*.png`
  screenshots, `backups/`, `backend_backup/`, `frontend_backup/`.
- Keep all existing video features intact. Image + TTS are **added**, not replacing.
- Re-init git in the copy (or copy `.git`); commits scoped to the copy.

## 3. Engine generalization (Phase 0 — main agent, before subagents)

The current engine hardcodes a 2-model video pair (`generate_seedance` vs
`generate_omni`) in `sxs_pipeline.py`, and the voting/leaderboard endpoints assume video.
Generalize so all three modalities share one voting/leaderboard/report core:

- Add a **`modality`** field (`"video" | "image" | "audio"`) to every job document and
  every vote document. Default existing jobs/votes to `"video"` (backfill on read).
- Generalize these endpoints to filter by an optional `?modality=` query param (default
  `video` for backward compatibility):
  `/api/sxs/pair`, `/api/sxs/vote`, `/api/sxs/stats`, `/api/sxs/leaderboard/users`,
  `/api/sxs/report.json`, `/api/sxs/report.csv`, `/api/sxs/jobs`.
- New pipelines (`image_pipeline.py`, `tts_pipeline.py`) follow the exact shape of
  `sxs_pipeline.py`: `create_*_job` → `process_job` (parallel 2-model gen) →
  `run_*_evaluation` (AI judge) → Firestore writes + `jobs_manager.invalidate_cache()`.
- Firestore collections reused: `eval_jobs` (with `modality`), `votes` (with `modality`).
  Media to existing GCS bucket under `images/` and `audio/` prefixes.

## 4. Image track (Subagent A)

### 4.1 Providers

**`backend/providers/gemini_image_provider.py`** — T2I + I2I via `google.genai`:
```python
from google import genai
client = genai.Client(vertexai=True, project=PROJECT_ID, location="global")  # service-account ADC
```
- Models: `gemini-3.1-flash-image`, `gemini-3-pro-image`, `instant-ramen`.
- T2I: text prompt → image bytes. I2I: prompt + input image part (inline base64, like
  `omni_provider._image_part_from_url`) → edited image bytes.
- Decode output image → upload to GCS `images/` → return `{model, url, latency_ms, status}`
  via a shared `_standard_result` helper.

**`backend/providers/gpt_image_provider.py`** — GPT2 / GPT-image via FAL (`fal_client`,
`FAL_KEY` already in env). T2I + edit (I2I). Quality tier param `low | medium | high`.
Reuse `fal_provider._ensure_accessible_to_fal` to proxy GCS input images to FAL. Confirm
exact FAL slug (e.g. `fal-ai/gpt-image-1` / `.../edit`) against FAL docs at build time;
isolate the slug + quality-param mapping in one constant block.

### 4.2 Matchup registry (default, toggleable like the video model registry)

| # | Gemini side | GPT2 (FAL) tier |
|---|-------------|-----------------|
| 1 | `gemini-3.1-flash-image` | GPT2 **medium** |
| 2 | `gemini-3-pro-image` | GPT2 **high** |
| 3 | `instant-ramen` | GPT2 **low** |

Each case names its matchup (or defaults to #1). The job stores both sides' results with
neutral labels A/B for blind voting; the model identity is hidden in the voter UI and only
revealed in admin/leaderboard.

### 4.3 Cases JSON (image)

```json
{
  "cases": [
    { "id": "c1", "mode": "t2i", "prompt": "a koi pond at dusk, cinematic",
      "matchup": "gemini-3.1-flash-image_vs_gpt2-medium" },
    { "id": "c2", "mode": "i2i", "prompt": "make it snow",
      "input_image": "ref/koi.png", "matchup": "gemini-3-pro-image_vs_gpt2-high" }
  ]
}
```
Optional asset files uploaded alongside (reusing `util.asset_intake`:
`save_uploads_to_temp` → `upload_assets_to_gcs` → `rewrite_case_assets`) resolve relative
`input_image` paths to GCS URLs.

### 4.4 AI judge (image)

`backend/image_evaluator.py` `run_image_evaluation(job)` using Gemini multimodal
(`gemini-2.5-flash`/`3.x`) scoring 1–5 per metric on each side + a pairwise winner:
- **Prompt following**, **Aesthetic quality**, **Detail / sharpness**, **Artifact-free**,
- **Edit fidelity** (I2I only: did it apply the edit while preserving the rest?).

### 4.5 Routes

- `POST /api/image/upload` (admin) — cases JSON + asset files → jobs (mirrors
  `/api/sxs/upload`).
- `GET /api/image/jobs`, `GET /api/image/jobs/{id}`, `POST .../retry`, `DELETE .../{id}`.
- Voting/leaderboard/report via the generalized `modality=image` endpoints.

### 4.6 Frontend — `/image-sxs`

- Admin: upload cases JSON + drag-drop reference images, run, job status table (reuse
  existing admin job-table components).
- Blind eval: side-by-side **image A / image B** with the per-metric rating widget reused
  from the video SxS page; submit → `/api/sxs/vote?modality=image`.
- Results: matchup win-rates + per-metric breakdown (reuse analytics components).
- Add `Image SxS` to the nav.

## 5. TTS track (Subagent B)

### 5.1 Providers

**`backend/providers/gemini_tts_provider.py`** — Gemini 3.1 Flash TTS:
```python
client = genai.Client(vertexai=True, project=PROJECT_ID, location="global")
interaction = client.interactions.create(
    model="gemini-3.1-flash-tts-preview",
    input=prompt_text,                      # may include director's notes + [audio tags]
    response_format={"type": "audio"},
    generation_config={"speech_config": speech_config},  # single or multi-speaker
)
pcm = base64.b64decode(interaction.output_audio.data)    # 24kHz mono 16-bit PCM
```
Full controls exposed:
- **voice**: any of the 30 prebuilt voices (Kore, Puck, Zephyr, …).
- **multi-speaker**: up to 2 `{"speaker": name, "voice": v}` entries; speaker names must
  match names used in the transcript.
- **style / director's notes**: free-text prepended to the transcript (Audio Profile /
  Scene / Director's Notes structure).
- **audio tags**: inline `[whispers]`, `[shouting]`, `[laughs]`, `[excited]`, etc.
- **language**: auto-detected; optional hint field.
- Wrap PCM → WAV (24kHz/mono/16-bit) → upload to GCS `audio/`.
- Implement **retry logic** (model occasionally 500s / returns text tokens) and a clear
  synthesis preamble to avoid the prompt-classifier false-rejection failure mode noted in
  the TTS docs.

**`backend/providers/elevenlabs_provider.py`** — ElevenLabs TTS via REST
(`https://api.elevenlabs.io/v1/text-to-speech/{voice_id}`), `ELEVENLABS_API_KEY` from env.
Model **`eleven_multilingual_v2`** (default). Map controls to nearest
equivalents: voice → ElevenLabs voice_id; style/emotion → voice_settings
(stability / similarity / style); pace → handled via text/SSML where supported. Output
mp3/pcm → GCS `audio/`.

### 5.2 Cases JSON (tts)

```json
{
  "cases": [
    { "id": "t1", "text": "[cheerful] Have a wonderful day!",
      "voice": "Kore", "style_prompt": "Warm, upbeat morning-radio host.",
      "language": "en" },
    { "id": "t2", "mode": "multi",
      "text": "Joe: How's it going?\nJane: Not bad!",
      "speakers": [ {"speaker":"Joe","voice":"Kore"}, {"speaker":"Jane","voice":"Puck"} ],
      "style_prompt": "Casual chat between friends." }
  ]
}
```
Gemini gets `style_prompt` + `text` + tags + `speech_config`. ElevenLabs gets the
equivalent voice + settings + cleaned text (tags stripped or mapped).

### 5.3 AI judge (audio)

`backend/tts_evaluator.py` `run_tts_evaluation(job)` — Gemini multimodal audio judge
scoring each side 1–5 + winner on: **Naturalness**, **Style/prompt adherence**,
**Expressiveness**, **Pacing**, **Pronunciation/clarity**.

### 5.4 Routes

- `POST /api/tts/upload` (admin) — cases JSON → jobs.
- `GET /api/tts/jobs`, `/{id}`, retry, delete.
- Voting/leaderboard/report via generalized `modality=audio` endpoints.

### 5.5 Frontend — `/tts-sxs`

- Admin: cases JSON upload + a control form (voice dropdown of 30 voices, style/director's
  notes textarea, audio-tag helper, multi-speaker toggle, language) to compose/preview a
  case; run; job status table.
- Blind eval: A / B `<audio controls>` players + per-metric rating widget; submit →
  `/api/sxs/vote?modality=audio`.
- Results: Gemini-vs-ElevenLabs win-rates + per-metric breakdown.
- Add `TTS SxS` to the nav.

## 6. Eval = human blind SxS **+** AI judge for both modalities (mirrors existing dual flow).

## 7. Configuration / secrets

`backend/.env` in the copy (gitignored — never commit):
- Reuse existing: `GCP_PROJECT_ID`, `GCS_BUCKET_NAME`, `FAL_KEY`, `OUTPUT_GCS_BUCKET`,
  `ADMIN_USER`, `ADMIN_PASS`, service-account ADC (`GOOGLE_APPLICATION_CREDENTIALS`).
- Add: **`ELEVENLABS_API_KEY`** (value provided privately by user; store only in `.env`).
- Google calls (Gemini image, instant-ramen, Gemini TTS) use **service-account ADC** via
  `genai.Client(vertexai=True, ...)` — no API key in code.
- Add `elevenlabs` (or just `requests`) to `requirements.txt`; `google-genai==1.64.0`
  already present and supports `interactions`.

## 8. Build orchestration (parallel subagents)

- **Phase 0 (main agent):** copy project; engine generalization (modality field + generic
  endpoints); `.env` + `requirements.txt` scaffolding; verify backend boots + existing
  video flow still works.
- **Phase 1 (two parallel subagents):**
  - **Subagent A — Image:** `gemini_image_provider.py`, `gpt_image_provider.py`,
    `image_pipeline.py`, `image_evaluator.py`, `/api/image/*` routes, `/image-sxs` page.
  - **Subagent B — TTS:** `gemini_tts_provider.py`, `elevenlabs_provider.py`,
    `tts_pipeline.py`, `tts_evaluator.py`, `/api/tts/*` routes, `/tts-sxs` page.
  - Subagents touch disjoint files; shared files (`main.py` route registration, nav)
    edited by main agent after subagents return, to avoid conflicts. Alternatively each
    track registers routes via its own `APIRouter` module included in `main.py`.
- **Phase 2 (main agent):** wire nav + route includes, run backend + frontend, smoke-test
  each modality end-to-end (upload tiny cases JSON → generate → vote → leaderboard),
  capture screenshots, fix integration issues.

## 9. Testing / verification

- Per provider: a small script that generates one sample and confirms a playable/viewable
  GCS artifact (mirrors existing `test_*.py` convention).
- One end-to-end smoke per modality: 1-case JSON → job completes → AI scores present →
  `/pair` serves it → vote records → leaderboard updates.
- Verify the existing **video** flow is unbroken after generalization (regression).

## 10. Out of scope (v1 / YAGNI)

- TTS streaming playback (generate-then-store is enough for SxS).
- More than 2 speakers (Gemini limit is 2).
- Auto prompt-expansion (could later reuse the `prompt-expand` skill).
- New auth / multi-tenant changes.

## 11. Open confirmations (resolve during spec review)

1. Exact FAL slug + quality-param name for GPT2/GPT-image T2I and edit.
2. ElevenLabs model = **`eleven_multilingual_v2`** (confirmed). Default voice_ids TBD at build.
3. Whether image matchups should be the 3 fixed pairs only, or a fully open registry
   (default: 3 fixed pairs, registry-backed so more can be toggled later).
