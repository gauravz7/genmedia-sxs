# Data Intake API

Two standard ways to get a customer's data into a GenMedia SxS duel, for each of
the three modalities:

| | endpoint | you supply | we do |
|---|---|---|---|
| **BYOP** — bring your prompts | `POST /api/{sxs,image,tts}/prompts` | prompts + the model names to run | generate the media, judge it, put it in the arena |
| **BYOO** — bring your outputs | `POST /api/{sxs,image,tts}/outputs` | prompts + URLs to media you already generated | rehost the media, judge it, put it in the arena |

`sxs` = **video**, `image` = image, `tts` = speech. Either way the case becomes
an ordinary job doc: it shows up in the blind A/B arena, in the AI-judge
verdicts, and in the win-rate / latency / agreement analytics, indistinguishable
from a job the platform generated itself except for its `origin` field.

- **Base URL (prod):** `https://genmedia-sxs-v2-440790012685.us-central1.run.app`
- **Base URL (local):** `http://localhost:8011`

---

## Authentication

All six endpoints are admin-only. Get a token once, send it as `X-Admin-Token`:

```bash
BASE=http://localhost:8011
TOKEN=$(curl -s -X POST "$BASE/api/admin/login" \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<ADMIN_PASS>"}' | jq -r .token)

curl -X POST "$BASE/api/image/prompts" \
  -H "X-Admin-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d @request.json
```

---

## Which model names can I use?

Model names are checked against the shared registry. An unknown or deactivated
name is rejected with `400` — it never becomes a job that silently produces
nothing. List what is currently accepted (no auth needed):

```bash
curl -s "$BASE/api/intake/models?modality=image" | jq
```

```json
{"models": [
  {"id": "gemini-3-pro-image", "name": "Gemini 3 Pro Image", "modality": "image",
   "type": "t2i", "provider": "gemini", "transport": "vertex",
   "quality": null, "is_active": true}
]}
```

`modality` is one of `video`, `image`, `tts` (omit it for all three).
`transport` reflects the platform rule: **every Google model runs on Vertex AI,
every non-Google model runs through FAL.**

Admins can register more models at `POST /api/models` (see `backend/README.md`).

### How many models per case

| modality | models per duel | why |
|---|---|---|
| video | **any number** (≥1) | video jobs key `results` by model id and pick two at random at read time |
| image | **exactly 2** | the job doc is two-sided — `results` keyed `A`/`B` with a `side_map` |
| tts | **exactly 2** | same |

Passing 1 or 3 models to image/tts is a `400`, not a truncation.

---

## The response envelope

All six endpoints return the same shape:

```json
{
  "status": "ok",
  "batch_id": "image_intake_1785914380",
  "job_ids": ["img_acme-001_1785914356594_652"],
  "count": 1,
  "skipped": [
    {"index": 3, "id": "acme_004", "reason": "'ghost-model' is not a registered model"}
  ]
}
```

**One bad row does not abort the batch.** A 500-case upload with two malformed
rows produces 498 jobs and two entries in `skipped`. `status` is `"failed"` only
when *nothing* could be created. Errors that apply to the whole request — no
cases, a bad model name in the request-level `models` list, missing auth — are
`4xx` responses instead.

Generation is asynchronous: `/prompts` returns as soon as the jobs are created.
Poll `GET /api/{sxs,image,tts}/jobs` and watch `results[*].status` and
`auto_eval_status` (`pending` → `running` → `done`).

| field | type | meaning |
|---|---|---|
| `status` | `"ok" \| "failed"` | `"failed"` only when nothing could be created |
| `batch_id` | string | echoed, or the generated one |
| `job_ids` | string[] | Firestore doc ids created, in case order |
| `count` | int | `len(job_ids)` |
| `skipped` | object[] | `{index: int, id: string, reason: string}` per rejected case. `id` falls back to `"(case #N)"` |

### Status codes

| code | when |
|---|---|
| `200` | the envelope above |
| `400` | no cases; an unusable model name; the wrong model count for a two-sided modality |
| `401` | missing or wrong `X-Admin-Token` |
| `422` | body doesn't parse (e.g. `models` omitted on `/prompts`) |

An unusable model name reports **every** problem at once, and lists what *is*
available:

```json
{"detail": {"error": "Unusable model(s) requested.",
            "problems": ["'ghost-model' is not a registered model",
                         "'gemini-3-pro-image' is a image model, not tts"],
            "available": ["elevenlabs-v3", "gemini-3.1-flash-tts-preview"]}}
```

---

## 1. BYOP — `POST /api/{sxs,image,tts}/prompts`

```json
{
  "models": ["gemini-3-pro-image", "gpt-image-2-high"],
  "cases": [ ... ],
  "run_eval": true,
  "batch_id": "acme-q3"
}
```

| field | required | meaning |
|---|---|---|
| `models` | yes | registry ids, applied to **every** case in the request |
| `cases` | yes | see the per-modality schemas below |
| `run_eval` | no (default `true`) | run the AI judge once generation finishes |
| `batch_id` | no | your own label; auto-generated if omitted |

### Video — `POST /api/sxs/prompts`

```json
{
  "models": ["seedance-2-0-t2v", "omni-preview-t2v"],
  "cases": [{
    "id": "acme_v001",
    "customer": "acme",
    "prompt": "A cyclist rides through neon-lit rain, slow dolly-in",
    "modality": "T2V",
    "aspect_ratio": "16:9",
    "duration": 8,
    "categories": ["automotive", "night"]
  }]
}
```

| field | required | notes |
|---|---|---|
| `id` | yes | unique case id. **Embeds the customer name — never rendered in full in the UI** (see `maskPid()`) |
| `prompt` | yes | the generation instruction |
| `modality` | yes | `T2V`, `I2V`, `FLF2V`, `V2V`, `Ref2V` — maps to the registry types `t2v` / `i2v` / `r2v` |
| `customer` | no | grouping key for analytics |
| `aspect_ratio` | no | e.g. `16:9`, `9:16` (default `16:9`) |
| `duration` | no | seconds |
| `reference_images` | i2v / r2v | list of URLs — first frame, last frame, or subject references |
| `reference_videos` | v2v / r2v | list of URLs |
| `categories` | no | tags used by the analytics filters |

Video models are **type-specific**. Every model you name must match the case's
own type, or the request is rejected for that case — a `t2v` model on an `I2V`
case would ignore the reference image and produce a duel that isn't comparing
what it claims to.

### Image — `POST /api/image/prompts`

**T2I vs I2I is a property of the case, not of the model.** One registered `t2i`
model serves both; the pipeline switches on whether the case has an
`input_image`.

```json
{
  "models": ["gemini-3-pro-image", "gpt-image-2-high"],
  "cases": [
    {"id": "acme_i001", "mode": "t2i",
     "prompt": "A single red maple leaf on white, studio product photo",
     "aspect_ratio": "1:1"},

    {"id": "acme_i002", "mode": "i2i",
     "prompt": "Make it snow heavily and add a warm sunset glow",
     "input_image": "https://storage.googleapis.com/acme-share/koi.png"}
  ]
}
```

| field | required | notes |
|---|---|---|
| `id` | yes | unique case id |
| `prompt` | yes | generation or edit instruction |
| `mode` | no | `t2i` (default) or `i2i`. Also accepted as `modality`; `edit` / `image-to-image` are aliases for `i2i` |
| `input_image` | **i2i** | URL of the source image. `reference_image` and `input_images[0]` also accepted. Rehosted into our bucket so the judge can read it |
| `aspect_ratio` | no | e.g. `1:1`, `16:9` |
| `resolution` | no | free-form |
| `customer`, `categories` | no | as above |

An `i2i` case adds an **edit-fidelity** criterion to the AI judge.

### TTS — `POST /api/tts/prompts`

**Single- vs multi-speaker is a property of the case, not of the engine.** Both
engines render whichever the case asks for.

```json
{
  "models": ["gemini-3.1-flash-tts-preview", "elevenlabs-v3"],
  "cases": [
    {"id": "acme_t001", "mode": "single",
     "text": "Welcome to the quarterly review.",
     "voice": "George", "language": "en",
     "style_prompt": "warm, measured, corporate narrator"},

    {"id": "acme_t002", "mode": "multi",
     "text": "Priya: Did the shipment clear customs?\nRahul: Cleared this morning — it's on the truck.",
     "speakers": [{"name": "Priya"}, {"name": "Rahul"}],
     "language": "hi-en"}
  ]
}
```

| field | required | notes |
|---|---|---|
| `id` | yes | unique case id |
| `text` | yes | the script. For multi-speaker, one `Name: line` per line |
| `mode` | no | `single` (default) or `multi` |
| `speakers` | **multi** | `[{"name": "..."}, ...]`. Each distinct name gets its own voice, in order of first appearance |
| `voice` | no | single-speaker only — a curated name (`George`, `Sarah`, `Rachel`, …) or a raw voice id |
| `language` | no | BCP-47-ish code. **Autodetected from `text` when omitted.** A mixed tag like `hi-en` routes generation to the local language (`hi`) while the full tag is kept for filtering |
| `style_prompt` | no | delivery direction; also drives ElevenLabs' stability tier |
| `customer`, `categories` | no | categories are auto-tagged from language + industry when omitted |

Inline audio tags (`[excited]`, `[whispers]`, `[applause]`) are understood by
ElevenLabs v3 and stripped for engines that don't support them.

---

## 2. BYOO — `POST /api/{sxs,image,tts}/outputs`

Use this when the customer has already generated the media and just wants it
scored and voted on.

```json
{
  "cases": [ ... ],
  "run_eval": true,
  "batch_id": "acme-q3-import",
  "source_label": "Acme Q3 export, 2026-08-01"
}
```

There is **no request-level `models` list** — each case carries its own
`outputs` manifest. A customer export is rarely uniform: one case may compare
A vs B and the next B vs C.

### The `outputs` manifest

Keys are registry model ids; values are the media the customer produced with
that model. Long form:

```json
"outputs": {
  "gemini-3-pro-image": {
    "url": "https://acme.example.com/exports/001-gemini.png",
    "latency_ms": 4200,
    "metadata": {"seed": 12345, "run": "batch-7"}
  },
  "gpt-image-2-high": {"url": "gs://acme-share/exports/001-gpt.png"}
}
```

Shorthand, when you only have URLs:

```json
"outputs": {
  "gemini-3-pro-image": "https://acme.example.com/exports/001-gemini.png",
  "gpt-image-2-high":   "gs://acme-share/exports/001-gpt.png"
}
```

| field | required | notes |
|---|---|---|
| `url` | yes | `https://`, `http://`, or `gs://` |
| `latency_ms` | no | the customer's own generation time — feeds the latency analytics. Omit rather than guess |
| `metadata` | no | free-form; stored on the result and never interpreted |

Everything else about the case is exactly the schema documented under BYOP for
that modality — same `id`, `prompt`/`text`, `mode`, `speakers`,
`reference_images`, and so on. The judge needs that context to score the media.

### What happens to the URLs

Every URL is **downloaded and rehosted into our GCS bucket** (`sxs/ingest/`,
`images/ingest/`, `audio/ingest/`). This is not optional: signed links expire,
third-party hosts disappear, and both the AI judge and the authenticated
`/api/media` proxy read through GCS. Reference and `input_image` assets are
rehosted too.

A URL that is *already* in our bucket is passed through untouched.

Give us URLs we can actually reach: a public link, a signed link that is still
valid, or a `gs://` path readable by the service account. An unreachable URL is
reported in `skipped` for that case.

### Example — video

```json
{
  "cases": [{
    "id": "acme_v001",
    "customer": "acme",
    "prompt": "A cyclist rides through neon-lit rain, slow dolly-in",
    "modality": "T2V",
    "aspect_ratio": "16:9",
    "outputs": {
      "seedance-2-0-t2v": {"url": "https://acme.example.com/001-seedance.mp4", "latency_ms": 51000},
      "omni-preview-t2v": {"url": "gs://acme-share/001-omni.mp4", "latency_ms": 63000}
    }
  }]
}
```

### Example — TTS, multi-speaker

```json
{
  "cases": [{
    "id": "acme_t002",
    "mode": "multi",
    "text": "Priya: Did the shipment clear customs?\nRahul: Cleared this morning.",
    "speakers": [{"name": "Priya"}, {"name": "Rahul"}],
    "language": "hi-en",
    "outputs": {
      "gemini-3.1-flash-tts-preview": "https://acme.example.com/t002-gemini.mp3",
      "elevenlabs-v3": "https://acme.example.com/t002-eleven.mp3"
    }
  }]
}
```

Ingested jobs are marked `origin: "ingest"` with your `source_label` in
`imported_from`, and each result carries `"ingested": true`.

---

## The `run_eval` flag

`run_eval` (default `true`) controls the AI judge on both paths. With
`run_eval: false` the job is created and votable by humans, but
`auto_eval_status` is set to `"skipped"` and no judge runs — useful when you
only want human votes, or when you're loading a large archive and want to judge
it later.

You can always run the judge afterwards from the admin UI, per job.

---

## Known limits

- **Image and TTS duels are structurally two-sided.** Comparing three image
  models means three separate pairwise requests.
- **Ingested jobs skip image auto-tagging.** Generated image jobs get taxonomy
  tags automatically; ingested ones do not. Supply `categories` on the case, or
  those jobs will be missing from tag-filtered analytics.
- **Case ids embed customer names**, so the UI only ever shows the last 4
  characters. Don't put anything in an id you wouldn't want partially visible.
- **Rehosting is synchronous.** A batch of several hundred large videos will
  take a while to return; split very large imports into a few requests.

---

## See also

- `docs/api/API_REFERENCE.md` — the rest of the API
- `backend/README.md` — the same contract as a formal spec (typed field tables,
  status codes, and the job doc each endpoint writes), plus data model,
  providers, and registry admin
- `EVAL_GUIDE.md` — running and scoring an evaluation end to end
