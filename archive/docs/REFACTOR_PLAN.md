# GenMedia SxS — Refactor Plan

**Companion to:** `docs/TECHNICAL_PRD.md`
**Goal:** Evolve the current working-but-coupled build into a modular, testable, multi-tenant **evaluation harness** that enterprises can run continuously against their own models — without a big-bang rewrite.
**Last updated:** 2026-07-22

---

## 1. Guiding principles

1. **Incremental & always-shippable.** Every phase leaves the app deployable. No phase is allowed to change externally-observable behavior *except* the phases explicitly labeled "feature."
2. **Refactor before feature.** Phases 0–6 are internal restructuring that unlock the PRD's enterprise features (Phases 7–8). Do not build Prompt Suites / BYOO on top of the current coupled core.
3. **Contracts at the seams.** The PRD's core insight — *decouple prompt → generation/ingestion → evaluation* — is realized by introducing typed contracts (dataclasses/pydantic models) at each boundary, then swapping implementations behind them.
4. **Characterize, then change.** Add a test safety net around current behavior *first* (there is none today), so refactors are verifiable.

---

## 2. Current-state pain points (measured)

| Pain | Evidence | Consequence |
|---|---|---|
| No shared infra clients | **76** Firestore client constructions (37 in `main.py`) | Impossible to swap datastore per tenant; connection churn; untestable. |
| Scattered config | **~90** `os.getenv` calls (54 in `main.py`) | No validation, no per-tenant config, hidden coupling to project/bucket/collection names. |
| Hardcoded provider dispatch | `generate_seedance` / `generate_omni` / `_gen_side` / `generate_for_model`, `SEEDANCE_KEY` const | Adding a model or a BYOO side means editing pipeline internals; no hybrid matchups. |
| Generation ≡ evaluation | `upload` → `BackgroundTasks(process_batch)` → judge, all one flow | Can't evaluate pre-generated content; can't run judge-only. |
| Ephemeral orchestration | image/tts use FastAPI `BackgroundTasks` | Work dies on instance restart; no durable retry/resume at scale. |
| Monolith | `main.py` = **2868** lines mixing video routes + admin + analytics + media + slides | Hard to navigate, test, or assign ownership. |
| Result schema drift | video `latency` (s) vs image/tts `latency_ms` (ms), normalized ad hoc in analytics | Every consumer re-normalizes; fragile. |
| Zero tests / CI | no test files, `ignoreBuildErrors: true` in `next.config.ts` | No safety net; refactoring is high-risk. |

---

## 3. Target architecture

```
backend/app/
  config.py            # pydantic Settings — single source for all env/config
  deps.py              # FastAPI deps: settings, require_admin, current tenant
  infra/
    firestore.py       # cached client + collection accessors (tenant-aware)
    gcs.py             # storage + signed URLs + media proxy helpers
    genai.py           # shared Vertex genai client factory
  domain/
    models.py          # Case, ModelSpec, Suite, Execution, Comparison, Vote, Verdict
    repositories.py    # JobRepository / VoteRepository (per modality, shared base)
  providers/
    base.py            # Provider protocol + registry
    vertex.py fal.py omni.py gemini_image.py gpt_image.py mai_image.py
    gemini_tts.py elevenlabs.py
  services/
    suite.py           # Prompt Suite CRUD/validation/coverage      (Phase 7)
    generation.py      # run providers for a matchup -> Job
    ingestion.py       # BYOO: manifest + asset intake -> Job        (Phase 5/7)
    evaluation.py      # judges (core5/director/image/tts) -> Verdict
    analytics.py       # latency / winmap / agreement (from repos)
    orchestrator.py    # durable job state machine                   (Phase 6)
  evaluators/          # (existing judge logic, thinned to pure fns)
  routers/
    video.py image.py tts.py analytics.py admin.py media.py slides.py suites.py
  main.py              # thin create_app(): wire routers + static mount
```

Execution-centric flow (executions are the primitive; comparisons are derived — see §9):

```
Prompt Suite ─┬▶ Generation ──┐
   (Phase 7)  └▶ Ingestion(BYOO)┴▶ Execution[]  ──▶  Evaluation ──▶ Arena + Analytics
   uploads: prompts OR outputs   (cached, deduped)   mode: absolute|pairwise|both
```

- Upload accepts **prompts** (generate the executions) or **outputs** (BYOO — ingest as executions). Either way the substrate is the same `Execution[]`.
- The operator picks an **eval mode** per run: `absolute` (per-execution scores), `pairwise` (derived comparisons), or `both`.
- Executions are **never regenerated** when the (prompt, model, params) already ran — see the no-rerun guarantee in §9.

---

## 4. Phased plan

Each phase lists **goal · key changes · touched files · verification · unlocks**. Effort is a rough T-shirt size.

### Phase 0 — Safety net & scaffolding  · **S–M** · *(no behavior change)*
- **Goal:** make refactoring verifiable.
- **Changes:**
  - Add `pytest`; write characterization tests for the pure/high-value logic: `_wilson`, `benchmark_winmap` family detection, `analytics_agreement`, `classify_image_categories` fallback, `side_map`→winner resolution, `_job_status` / dedup keys.
  - Add API smoke tests (FastAPI `TestClient`) for `/api/health`, `/pair`, `/vote` (dupe window), `/stats` with a Firestore emulator or a thin repo fake.
  - Add `ruff` + `black`; introduce `backend/pyproject.toml`; pin `Pillow` (currently unpinned).
  - Add CI (GitHub Actions): lint + tests + `next build`/`lint`. (Repo is on `master` with a large uncommitted changeset — land a clean checkpoint commit before starting.)
- **Verification:** tests green; CI passing on a no-op PR.
- **Unlocks:** everything below.

### Phase 1 — Centralize configuration  · **S** · *(no behavior change)*
- **Goal:** one typed, validated config surface.
- **Changes:** `app/config.py` with pydantic-settings `Settings` covering every var in PRD §14 (project, bucket, per-modality collections, judge models/locations, provider keys, concurrency). Replace the ~90 `os.getenv` sites with `get_settings()`.
- **Verification:** app boots with identical env; a config-snapshot test asserts defaults match today's literals (e.g. `sxs_jobs`, `gemini-3.5-flash`).
- **Unlocks:** multi-tenancy & data-residency (swap project/bucket/collections per tenant).

### Phase 2 — Centralize infrastructure clients & repositories  · **M** · *(no behavior change)*
- **Goal:** kill the 76 client constructions; put datastore behind an interface.
- **Changes:** `infra/firestore.py` (cached client + `collection(modality, kind)` accessor), `infra/gcs.py`, `infra/genai.py`. Introduce `JobRepository`/`VoteRepository` with a shared base; migrate `main.py` analytics + pipelines + evaluators to read/write through repos instead of inline `.collection(...).stream()`.
- **Verification:** characterization tests from Phase 0 still green against the repo layer; diff shows analytics results byte-identical on a fixture dataset.
- **Unlocks:** tenant-scoped collections, caching/pre-aggregation later, testability.

### Phase 3 — Break up the `main.py` monolith  · **M** · *(no behavior change)*
- **Goal:** symmetry across modalities; thin app factory.
- **Changes:** extract video/"sxs" routes → `routers/video.py` (mirroring `image_routes`/`tts_routes`); split `analytics.py`, `admin.py`, `media.py`, `slides.py`. Move `require_admin` + shared deps → `app/deps.py`. `main.py` becomes `create_app()` (~150–200 lines) that includes routers **before** the static catch-all (preserve the `/api/*`-wins ordering and SPA 404 fallback).
- **Verification:** route inventory diff (dump `app.routes` before/after — identical paths/methods); smoke tests green.
- **Unlocks:** clear ownership; safe parallel work on each modality.

### Phase 4 — Unify the provider layer  · **M–L** · *(behavior-preserving)*
- **Goal:** one interface for all model calls; standardized result.
- **Changes:**
  - `domain/models.py`: `GenerationResult` (status, `media_uri`, `latency_s`, `cost?`, `width/height/duration/fps?`, `model_id`, `raw`, `error`) — **normalize latency to seconds here**, once.
  - `providers/base.py`: `Provider` protocol `async generate(case, spec) -> GenerationResult` + a registry keyed by the `provider` field in `models.json`.
  - Port `generate_seedance`, `generate_omni`, image `_gen_side`, `generate_for_model` into provider classes. Replace `SEEDANCE_KEY`/`omni_key` hardcoding with registry lookups.
  - Make `resolve_matchup` provider-agnostic: `Matchup = list[ModelSpec]`, each `ModelSpec` → a registered provider.
- **Verification:** golden test — same case in → same `results` doc out (modulo the new normalized fields); latency values equal previous seconds.
- **Unlocks:** add-a-model-without-touching-pipelines; **hybrid & BYOO matchups**.

### Phase 5 — Execution-centric core: decouple generation from evaluation  · **M–L** · *(enabler)*
- **Goal:** make the **Execution** the primitive (§9). Generation and ingestion both produce cached, deduped executions; comparisons and judging are derived on top. The judge/arena don't care how media was produced.
- **Changes:**
  - `domain/models.py`: add `Execution` and `Comparison`; retire the pair-baked `Job(side_map, results)` shape.
  - `services/generation.py` and `services/ingestion.py` both emit **`Execution` docs** (never a paired job). `source`: `generated | ingested`.
  - **No-rerun guarantee (§9):** deterministic `exec_id` = the idempotency key; `doc.create()` gives atomic dedup; skip on `status == success`; `force`/new-seed to override. Generalizes today's `_already_run_keys`.
  - `services/evaluation.py` supports **`absolute`** (per-execution, wraps `run_core5_evaluation`), **`pairwise`** (comparisons, wraps `run_director_pairwise` / image+tts judges), or **`both`** — mode chosen per run.
  - Comparisons formed **on-demand** by the arena (sample two executions of the same case, different models) or **materialized** selectively (e.g. all-vs-champion); votes/verdicts reference `execution_a`/`execution_b`.
  - Grow `util/asset_intake.py` → `services/ingestion.py`: register pre-generated media, **extract ground-truth `duration`/`fps`** (Core-5 depends on it), transcode to judge-friendly formats, content-hash.
- **Verification:** re-running a suite regenerates **zero** already-successful executions (cache report shows `reused = target`); an ingested execution yields a verdict identical in shape to a generated one; a new model runs only its column.
- **Unlocks:** BYOO (PRD Feature #2), continuous per-model onboarding (§9), absolute rankings, judge-only reruns.

### Phase 6 — Durable job orchestration  · **M** · *(reliability)*
- **Goal:** replace ephemeral `BackgroundTasks` with resumable work.
- **Changes:** `services/orchestrator.py` — a Firestore-backed job state machine (`pending→generating→judging→done/failed`, per-side) driven by Cloud Tasks or Pub/Sub (fall back to a resumable in-process worker if staying single-service). Fold in existing `resume`/`retry-failures` semantics and `_job_status` dedup.
- **Verification:** kill the instance mid-batch → work resumes with no duplicate generations (dedup key `customer|prompt_id`).
- **Unlocks:** reliability at scale; the continuous-eval push API.

### Phase 7 — Standardization features (PRD §Enterprise)  · **L** · *(features)*
- **Goal:** build the two requested features on the clean core.
- **Changes:**
  - **Prompt Suites (Feature #1):** `services/suite.py` + `routers/suites.py` — versioned, immutable suites; per-modality **JSON Schema validation** (enums, taxonomy-conformant categories, resolvable assets); coverage/balance report; forkable golden default suite.
  - **BYOO ingestion (Feature #2):** standardized **manifest** (JSON/CSV) → `services/ingestion.py`; preflight validator + quarantine report; connectors (GCS/S3/zip) + push webhook.
  - **Run manifest:** formalize `Run = Suite@version × ModelSet × JudgeConfig × time` (extends `SXS_RUNS_COLLECTION`) for reproducibility and regression tracking.
- **Verification:** publish a suite → generate a run → results pinned to the immutable suite hash; re-run reproduces the same case set.

### Phase 8 — Enterprise hardening  · **L** · *(features)*
- Multi-tenancy (tenant-scoped `Settings` + collection prefixes via Phases 1–2), **RBAC/SSO** replacing LDAP-freetext + single `ADMIN_PASS`, **configurable rubrics** (data-driven metric/weight config feeding the judges), **judge calibration** workflow (built on the existing agreement metric), analytics pre-aggregation/BigQuery rollups (avoids full-collection scans), data-residency config.

---

## 5. Refactor → PRD-feature mapping

| PRD enterprise feature | Prerequisite phases |
|---|---|
| Prompt Suites + validation + coverage (#1) | 1, 2, 3 → **7** |
| BYOO / pre-generated ingestion (#2) | 4, 5 → **7** |
| Hybrid matchups (our model vs vendor) | **4**, 5 |
| Continuous eval / push API / regression alerts | 5, **6**, 7 |
| Multi-tenancy / data residency | **1**, **2**, 8 |
| RBAC / SSO | 3 → **8** |
| Configurable rubrics + judge calibration | 4/5 (thin evaluators) → **8** |
| Scalable analytics | 2 → **8** |

---

## 6. Sequencing & dependencies

```
0 (safety net) ─▶ 1 (config) ─▶ 2 (infra/repos) ─▶ 3 (routers) ─┐
                                     └─▶ 4 (providers) ─▶ 5 (decouple) ─▶ 6 (orchestration)
                                                                   └────────────┬───────────┘
                                                                                 ▼
                                                              7 (suites + BYOO)  ─▶  8 (enterprise hardening)
```

- **Phases 0–3** are pure internal refactors — low risk, high enabling value; do them first and land them fast.
- **Phase 4** is the pivotal enabler (unblocks hybrid + BYOO). 
- **Phases 7–8** are where the PRD features actually ship.

---

## 7. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Behavior drift during refactor | Phase 0 characterization tests + route-inventory & analytics-fixture diffs on every phase. |
| Firestore-shape assumptions scattered in analytics | Centralize reads in repos (Phase 2) *before* touching analytics math. |
| Big-bang temptation | Enforce "one phase per PR, always deployable"; feature-flag Phases 5–7 (`source` branching) so old flow keeps working. |
| Provider parity regressions | Golden per-provider tests capturing today's `results` docs before porting (Phase 4). |
| `BackgroundTasks` → queue migration risk | Keep in-process path behind a flag; migrate one modality first. |
| Frontend coupling to loose response shapes | Freeze API response contracts in Phase 3 (schema/tests) before internal changes ripple out. |

---

## 8. Suggested first PRs

1. **PR-0a:** `git init` + CI skeleton + `pytest` + `ruff`/`black` + 6 characterization tests (Wilson, winmap family, agreement, taxonomy fallback, side_map winner, dedup key).
2. **PR-0b:** FastAPI `TestClient` smoke tests (`/health`, `/pair`, `/vote` dupe window) against a Firestore fake.
3. **PR-1:** `app/config.py` + mechanical `os.getenv` → `settings` migration (with the defaults-snapshot test).

These three are low-risk, touch no behavior, and immediately make the rest of the plan safe to execute.

---

## 9. Execution-centric evaluation model (revises Phases 5 & 7)

The current schema welds two model outputs into one job (`side_map` + `results.{engine}`). That makes onboarding a new model expensive (re-generate whole pairs) and prevents reuse. Instead, treat **prompts** and **models** as independent axes and the **Execution** as the atomic, cached primitive; **Comparisons** are derived.

### 9.1 Primitives

**`Execution`** — one `(case, model, params)` run; generated once, reused forever:
```jsonc
{ "id": "exec_<hash>",            // deterministic — see 9.3
  "suite_id": "...", "suite_version": "1.2",
  "case_id": "...", "prompt": "...", "modality": "t2v", "mode": "t2i|i2i|...",
  "categories": [...], "language": "...",
  "model_id": "gemini-...", "model_version": "...", "provider": "vertex",
  "params": { "seed": null, "aspect_ratio": "16:9", "resolution": "...", "duration": 8 },
  "input_assets": ["gs://..."],   // i2i/i2v/r2v — part of prompt identity
  "media_uri": "gs://...",
  "metadata": { "latency_s": 0.0, "cost": null, "width": 0, "height": 0, "duration": 0, "fps": 0 },
  "content_hash": "...",
  "absolute_eval": { "core5": { /* per-execution scores */ } },   // when mode ∈ {absolute, both}
  "status": "pending|generating|success|error", "error": null, "created_at": 0.0 }
```

**`Comparison` / `Vote`** — a derived relation referencing two executions (never a baked pair):
```jsonc
{ "id": "...", "case_id": "...",
  "execution_a": "exec_...", "execution_b": "exec_...",
  "winner_execution": "exec_...", "scores": {...},
  "source": "human|ai", "ldap": "...", "timestamp": 0.0 }
```

### 9.2 Eval modes (chosen per run, at upload)
Upload accepts **prompts** (generate) or **outputs** (BYOO — ingest); either produces `Execution[]`. The run then declares:
- **`absolute`** — run the per-execution judge (`run_core5_evaluation`) → per-model absolute scores. Ranks a model without needing any opponent. Cost ∝ executions.
- **`pairwise`** — form comparisons and run the pairwise judge (`run_director_pairwise` / image+tts) + blind human arena → head-to-head win-rates. Cost ∝ compared pairs.
- **`both`** — absolute on every execution + selected pairwise comparisons (recommended default).

### 9.3 The no-rerun guarantee (content-addressed execution cache)
```
exec_id = "exec_" + sha256( prompt_fingerprint | model_id | model_version | params_hash )[:24]
prompt_fingerprint = sha256( normalize(prompt) | mode | sorted(input_asset_hashes) )
params_hash        = sha256( canonical_json(resolved_params) )
```
- **`model_version` is mandatory** — an in-place model update must bump it, or stale outputs get reused. Providers that can't report a version use a manually-bumped registry field.
- **Seed:** explicit seed → in `params_hash` (distinct cached cells); unspecified → normalized to a sentinel so re-runs reuse the one execution instead of drawing fresh random generations.
- **Atomic dedup:** `exec_id` is the Firestore doc id; generation does `doc.create()` → `AlreadyExists` ⇒ reuse, don't generate. Race-safe across concurrent batches/instances.
- **Skip on success only:** `error` retryable; `pending/generating` joined (waited on), not duplicated. Generalizes `_already_run_keys` ("only `done` is skipped") to per-execution granularity.
- **Escape hatch:** `force=true` / new explicit seed creates a fresh execution.
- **Transparency:** batch launch reports `target = |cases|×|models|`, `reused`, `to_generate` before running — no silent skips.

### 9.4 New-model onboarding (the payoff)
```
register model → enqueue Suite × {model}  →  cache skips every existing cell,
generates only the new column  →  comparisons & rankings recompute for free.
```

### 9.5 Ranking & analytics upgrade
- **Absolute:** per-model score distributions per taxonomy/language segment (from `absolute_eval`).
- **Pairwise:** existing Wilson-CI win-rates for any head-to-head; win-map & human↔AI agreement recompute over comparisons-referencing-executions.
- **Global ranking:** **Bradley-Terry / Elo** over the sparse pairwise graph → one ordered leaderboard across all models even with incomplete coverage. Use champion-vs-challenger or active sampling to avoid the N² blow-up.

### 9.6 Migration / backfill
Split each existing pair-job: extract each `results.{engine}` side → an `Execution` (deriving `exec_id` from its case+model+params), convert the job → a `Comparison` referencing the two, and rewrite votes' `winner_model` → `winner_execution`. Idempotent (deterministic ids), so it can re-run safely.
