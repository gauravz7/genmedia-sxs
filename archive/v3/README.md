# GenMedia SxS — v3 (execution-centric refactor)

Clean-room rewrite of the v2 backend into the execution-centric model from
`docs/REFACTOR_PLAN.md` §9. **v3 does not import from or modify v2** — the v2
`backend/` and `frontend/` are untouched. This directory is standalone.

## Why v3

v2 couples prompt → generation → evaluation around *pairs*. v3 makes the
**Execution** — one `(case, model, params)` run — the atomic, cached primitive.
Comparisons and Votes are derived relations. Old prompts re-run on new models as
research ships them, and a model **never regenerates** an execution it already
produced (the no-rerun guarantee, `execution_id()` + atomic `create_if_absent`).

Eval works in three modes chosen at upload: `absolute`, `pairwise`, `both`.
Content can be **generated** by the platform or **ingested** (BYOO — bring your
own outputs).

## Layout

```
app/
  config.py            # central pydantic-settings (replaces ~90 os.getenv)
  domain/
    models.py          # Case, ModelSpec, Suite, Execution, Comparison, Vote, Verdict + execution_id()
    repositories.py    # DocStore protocol + Repository ABCs (create_if_absent = dedup)
  providers/base.py    # Provider protocol + registry (dispatch by id, not hardcoded branches)
  infra/               # firestore/gcs/genai clients + concrete repositories   [Agent 1]
  evaluators/          # core5 / director / image / tts judges (pure fns)        [Agent 3]
  services/            # generation (no-rerun), ingestion, evaluation, analytics, suite [Agents 3,4]
  routers/             # FastAPI routes per modality + analytics/admin/media    [Agent 5]
tests/
  conftest.py          # FakeDocStore + fixtures (no I/O)
  test_domain_execution.py  # locks the no-rerun identity contract
  test_config.py
```

## Running

```bash
cd v3
python3 -m pytest        # all tests, no network/GCP needed
ruff check .
```

## Status

Foundation contracts (config, domain, repositories, provider base, test fakes)
are in place and green. Infra, providers, evaluators, services, and routers are
built by parallel agents against these contracts.
