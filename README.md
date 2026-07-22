# GenMedia SxS

**Blind side-by-side (SxS) evaluation platform for generative-media models — image, video, and text-to-speech.**

Runs head-to-head blind A/B comparisons scored by both human voters and an automatic LLM-as-judge, then aggregates win-rates, latency, and quality signals into a shared analytics dashboard.

## What it does

- **Blind A/B arenas** for image, video, and TTS — model identities hidden, left/right randomized.
- **Human voting** with per-metric 1–5 scoring and an overall winner (A / B / tie).
- **Automatic LLM-as-judge** — a multimodal model scores each pair on modality-specific rubrics (image/video visual quality, prompt adherence, artifacts; TTS naturalness, expressiveness, pacing, pronunciation).
- **Analytics** — win-rates with 95% Wilson confidence intervals, generation latency (avg / p50), **human ↔ AI-judge agreement**, and a segmented **win-map** showing where each model family adds the most value (by category and language).
- **Multilingual TTS** — English, Hindi, Hinglish, and Hindi-Bengali, with a graceful multilingual fallback for any other language.
- **Controlled 30-category image taxonomy** for consistent tagging and filtering across the arena, AI evals, and analytics.

## Models compared

- **Image:** Gemini image (Pro / Flash / Flash-Lite) vs GPT-image-2 (low / medium / high) vs MAI-Image.
- **Video:** Veo, Seedance, Omni, Kling — across T2V, I2V, and R2V.
- **TTS:** Gemini TTS vs ElevenLabs v3 (single-speaker and multi-speaker dialogue).

## Architecture

```
┌──────────────────────────────────────────────┐
│                  Cloud Run                     │
│  ┌──────────────┐     ┌───────────────────┐   │
│  │  Next.js      │────▶│  FastAPI backend  │   │
│  │ (static build)│     │  uvicorn :8080    │   │
│  └──────────────┘     └─────────┬─────────┘   │
└────────────────────────────────┼──────────────┘
              ┌───────────────────┼────────────────────┐
      ┌───────▼──────┐   ┌────────▼─────────┐   ┌───────▼─────────┐
      │  Firestore    │   │  Object storage  │   │  Model + judge  │
      │ jobs / votes  │   │  (GCS)           │   │  APIs           │
      └──────────────┘   └──────────────────┘   └─────────────────┘
```

- **Frontend:** Next.js (static export) + React + Tailwind CSS, served by the backend.
- **Backend:** Python FastAPI orchestrating the model/judge APIs, Firestore, and object storage.
- **Database:** Firestore — isolated collections per modality: `sxs_jobs` / `image_jobs` / `tts_jobs` and their `*_votes`.
- **Storage:** Cloud Storage (GCS) for generated media, served via an authenticated media proxy.
- **Judge:** a multimodal model on Vertex AI (`gemini-3.5-flash`, high-thinking) for image / video / TTS.
- **Deployment:** a single unified Docker image on Cloud Run.

## Routes

| Route | Purpose |
|---|---|
| `/` | Landing hub |
| `/image-sxs`, `/video-sxs`, `/tts-sxs` | Blind human A/B arenas |
| `/ai-evals` | All AI-judge verdicts (per-model scores, winner) |
| `/analytics` | Win-rates + CIs, latency, agreement, win-map |
| `/leaderboard` | Top evaluators |
| `/admin` | JSON batch upload, model registry, generations |

## Selected API

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/{image,tts}/upload` | POST | Upload a cases JSON → generate + auto-judge (admin) |
| `/api/{sxs,image,tts}/pair` | GET | Fetch a blind A/B pair for voting |
| `/api/{sxs,image,tts}/vote` | POST | Record a blind human vote |
| `/api/{sxs,image,tts}/stats` | GET | Win-rates + per-metric scores |
| `/api/analytics/latency` | GET | Avg / p50 latency per model × modality |
| `/api/benchmark/winmap` | GET | Segmented win-map with Wilson CIs |
| `/api/analytics/agreement` | GET | Human vs AI-judge agreement |

## Input format (admin JSON upload)

Each modality accepts a JSON array of case objects (fields only — supply your own content):

- **Image:** `{ id, mode: "t2i"|"i2i", prompt, matchup, aspect_ratio?, input_image?, categories? }`
- **Video:** `{ id, prompt, modality: "t2v"|"i2v"|"r2v", aspect_ratio?, reference_images?, reference_videos?, categories? }`
- **TTS:** `{ id, text, voice, language, style_prompt?, mode?: "single"|"multi", speakers?, el_voice?, categories? }`

## Local development

```bash
# Backend env (NOT committed) — set in backend/.env:
#   GCP_PROJECT_ID, GCS_BUCKET_NAME, provider API keys, ADMIN_USER/ADMIN_PASS

# Build the frontend (static export served by FastAPI)
cd frontend && npm ci && npm run build

# Run the backend (serves API + static UI)
cd ../backend && uvicorn main:app --port 8080
```

Deploy the unified image with the provided deploy script (`deploy_v2.sh`).

## Repository notes

- **Credentials, generated media, and evaluation prompt datasets are intentionally not committed** (see `.gitignore`). Provide your own prompt sets and provider keys locally.
