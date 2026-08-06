# Data Import — Standardized JSON Contracts (BYOP + BYOO)

Both **bring-your-prompts** (BYOP) and **bring-your-outputs** (BYOO) import paths
in v3 speak JSON and share one vocabulary: the `Case` and `ModelSpec` schemas.
Everything is validated (pydantic v2) and **content-addressed**, so re-importing
the same `(case, model, params)` cell always resolves to the same `execution_id`
— no duplicates, no re-generation.

---

## Shared building blocks

### `Case` — one prompt row
```jsonc
{
  "id": "case_abc123",              // REQUIRED. IDs may embed customer names — mask to last 4 in UI.
  "prompt": "A red fox in snow",    // the prompt text; for TTS this is the script to speak
  "modality": "t2i",               // t2i | i2i | t2v | i2v | r2v | tts
  "mode": "t2i",                   // optional finer mode (e.g. t2i vs i2i)
  "language": null,                 // optional BCP-47-ish hint (mainly TTS)
  "categories": [],                 // optional tags used by analytics segments
  "input_assets": [],               // gs:// or https refs for i2i / i2v / r2v
  "params": {                       // free-form generation params (see below)
    "aspect_ratio": "16:9",
    "seed": 42,
    "voice": "Kore"                 // TTS voice name (Gemini) or ElevenLabs voice name/id
  },
  "customer": null,
  "suite_id": null,
  "suite_version": null
}
```

### `ModelSpec` — one model to run the case on
```jsonc
{
  "id": "gemini-3-1-flash-image-t2i",   // registry id (models.json key)
  "name": "Gemini 3.1 Flash Image (T2I)",
  "provider": "gemini",                  // dispatch key -> provider module
  "model_id": "gemini-3.1-flash-image",  // what the provider actually calls
  "model_version": "v1",                 // bumping this forks a NEW cell
  "type": "t2i",
  "is_active": true
}
```

**Provider dispatch keys** (`provider` field): `vertex`, `fal`, `omni` (video);
`gemini`, `gpt`, `mai` (image); `gemini_tts`, `elevenlabs` (TTS).

> Note on FAL image models: `model_id` is the FAL slug, e.g.
> `openai/gpt-image-2` or `microsoft/mai-image-2.5`. The provider appends
> `/edit` automatically for `i2i`.

---

## BYOP — bring your prompts (generate from a dataset)

Batch generation is per-modality. Submit an array of cases × specs; the
`GenerationService` materializes and dedups them into Executions.

```
POST /api/image/jobs
POST /api/tts/jobs
POST /api/video/jobs
```
```jsonc
{
  "suite_id": "my-suite-2026-07",     // optional grouping
  "cases":  [ Case, Case, ... ],       // JSON array
  "specs":  [ ModelSpec, ModelSpec ],  // every case is run against every spec
  "eval_mode": "both"                  // absolute | pairwise | both
}
```
Response:
```jsonc
{ "modality": "image", "suite_id": "...", "eval_mode": "both",
  "count": 12, "executions": ["exec_…", "exec_…"] }
```

Single-cell generation (what the UI uses):
```
POST /api/executions
{ "case": Case, "spec": ModelSpec, "params": { ... } }   // -> Execution
```

---

## BYOO — bring your outputs (register pre-generated media)

For media generated out of band. Registered as `source="ingested"`,
`status="success"`, with the **same** content-addressed identity as a generated
cell (so a generated and an ingested copy of the same cell are one Execution).

### Single
```
POST /api/executions/ingest
{ "case": Case, "spec": ModelSpec, "media_uri": "gs://…",
  "params": { ... }, "metadata": { ... } }               // -> Execution
```

### Batch  *(new — mirrors the BYOP array shape)*
```
POST /api/executions/ingest/batch
{ "items": [
    { "case": Case, "spec": ModelSpec, "media_uri": "gs://…", "metadata": {...} },
    { "case": Case, "spec": ModelSpec, "media_uri": "gs://…" },
    ...
]}
```
Response — **partial-success**: a row that fails schema validation OR
registration is reported in `errors` (by original index) without aborting the
rest of the batch:
```jsonc
{
  "received": 3,          // rows in the request
  "count": 2,             // rows successfully ingested (echoed per input item)
  "executions": ["exec_…", "exec_…"],
  "ingested": [ Execution, Execution ],
  "errors": [
    { "index": 1, "error": [ { "loc": ["media_uri"], "msg": "Field required" } ] }
  ]
}
```

`media_uri` should be a `gs://` URI in the `project-pulse` bucket (served to
clients only through the authenticated `/api/media` proxy — never expose raw
`gs://` to the browser). `https://` URIs from providers (e.g. FAL) are also
accepted and passed through.

---

## Dedup rules (both paths)

`execution_id = "exec_" + sha256(prompt_fingerprint, model_id, model_version, params_hash)[:24]`

- Same `(case, model, params)` → same id → **existing execution returned, media not overwritten**.
- Change `model_version`, any generation `param`, or the prompt → **new cell**.
- `seed` omitted resolves to `"unseeded"` and is part of the fingerprint.
