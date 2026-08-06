"""Tests for GenerationService — the no-rerun guarantee.

The crucial invariant: generating the same (case, spec, params) twice calls the
provider EXACTLY once and returns the same execution id. A new model_version is
a different cell and DOES generate again. Provider failures mark the execution
errored.
"""
from __future__ import annotations

import asyncio

import pytest

from app.config import Settings
from app.domain.models import (
    Case,
    ExecStatus,
    Execution,
    GenerationResult,
    Modality,
    ModelSpec,
    execution_id,
)
from app.infra.repositories import ExecutionRepository
from app.services.generation import GenerationService


class StubProvider:
    """Counts generate() calls so we can assert the no-rerun guarantee."""

    def __init__(self, provider_id: str = "stub", *, fail: bool = False,
                 error_status: bool = False) -> None:
        self.provider_id = provider_id
        self.calls = 0
        self.fail = fail
        self.error_status = error_status

    async def generate(self, case, spec, params=None) -> GenerationResult:
        self.calls += 1
        if self.fail:
            raise RuntimeError("boom")
        if self.error_status:
            return GenerationResult(status=ExecStatus.ERROR, error="provider said no")
        return GenerationResult(
            status=ExecStatus.SUCCESS,
            media_uri=f"gs://bucket/{case.id}-{spec.model_id}.png",
            latency_s=1.5,
            width=1024,
            height=1024,
            model_id=spec.model_id,
        )


def _service(store, provider: StubProvider) -> GenerationService:
    repo = ExecutionRepository(store, "executions")
    return GenerationService(repo, Settings(), provider_lookup=lambda _pid: provider)


def _case(**kw) -> Case:
    base = dict(id="c1", prompt="A red fox in snow", modality=Modality.T2I, mode="t2i")
    base.update(kw)
    return Case(**base)


def _spec(**kw) -> ModelSpec:
    base = dict(id="m1", provider="stub", model_id="imagen-4.0", model_version="v1")
    base.update(kw)
    return ModelSpec(**base)


# --- the no-rerun guarantee ------------------------------------------------
def test_generate_twice_calls_provider_once_same_id(store):
    provider = StubProvider()
    svc = _service(store, provider)
    case, spec = _case(), _spec()

    first = asyncio.run(svc.generate(case, spec))
    second = asyncio.run(svc.generate(case, spec))

    assert provider.calls == 1                     # generated once, reused after
    assert first.id == second.id == execution_id(case, spec)
    assert first.status == ExecStatus.SUCCESS
    assert first.media_uri == second.media_uri
    assert second.source == "generated"


def test_success_records_media_and_latency(store):
    provider = StubProvider()
    svc = _service(store, provider)
    ex = asyncio.run(svc.generate(_case(), _spec()))
    assert ex.media_uri == "gs://bucket/c1-imagen-4.0.png"
    assert ex.metadata["latency_s"] == 1.5
    assert ex.metadata["width"] == 1024


def test_new_model_version_generates_again(store):
    provider = StubProvider()
    svc = _service(store, provider)
    case = _case()

    a = asyncio.run(svc.generate(case, _spec(model_version="v1")))
    b = asyncio.run(svc.generate(case, _spec(model_version="v2")))

    assert provider.calls == 2      # distinct cell -> regenerated
    assert a.id != b.id


def test_explicit_params_are_distinct_cells(store):
    provider = StubProvider()
    svc = _service(store, provider)
    case = _case()
    asyncio.run(svc.generate(case, _spec(), params={"seed": 1}))
    asyncio.run(svc.generate(case, _spec(), params={"seed": 2}))
    assert provider.calls == 2


def test_unseeded_reuses_single_cell(store):
    provider = StubProvider()
    svc = _service(store, provider)
    case = _case()
    asyncio.run(svc.generate(case, _spec(), params={"seed": None}))
    asyncio.run(svc.generate(case, _spec(), params={}))
    assert provider.calls == 1


# --- error path ------------------------------------------------------------
def test_provider_exception_marks_error(store):
    provider = StubProvider(fail=True)
    svc = _service(store, provider)
    ex = asyncio.run(svc.generate(_case(), _spec()))
    assert ex.status == ExecStatus.ERROR
    assert "boom" in (ex.error or "")


def test_error_status_result_marks_error(store):
    provider = StubProvider(error_status=True)
    svc = _service(store, provider)
    ex = asyncio.run(svc.generate(_case(), _spec()))
    assert ex.status == ExecStatus.ERROR
    assert "provider said no" in (ex.error or "")


def test_reserve_reuses_ingested_without_provider(store):
    # Pre-seed a success execution (as if ingested) at the same id.
    provider = StubProvider()
    svc = _service(store, provider)
    case, spec = _case(), _spec()
    eid = execution_id(case, spec)
    existing = Execution(
        id=eid, case_id=case.id, model_id=spec.model_id,
        media_uri="gs://pre/existing.png", status=ExecStatus.SUCCESS, source="ingested",
    )
    ExecutionRepository(store, "executions").reserve(existing.model_dump(mode="json"))

    ex = asyncio.run(svc.generate(case, spec))
    assert provider.calls == 0                 # never regenerate an existing cell
    assert ex.media_uri == "gs://pre/existing.png"
    assert ex.source == "ingested"


# --- batch -----------------------------------------------------------------
def test_generate_batch_matrix(store):
    provider = StubProvider()
    svc = _service(store, provider)
    cases = [_case(id="c1"), _case(id="c2", prompt="a cat")]
    specs = [_spec(model_id="imagen-4.0"), _spec(model_id="imagen-5.0")]

    out = asyncio.run(svc.generate_batch(cases, specs))
    assert len(out) == 4
    assert provider.calls == 4
    assert len({e.id for e in out}) == 4


def test_generate_batch_dedups_repeats(store):
    provider = StubProvider()
    svc = _service(store, provider)
    cases = [_case(), _case()]  # identical case twice
    specs = [_spec()]
    out = asyncio.run(svc.generate_batch(cases, specs))
    assert len(out) == 2
    assert provider.calls == 1  # both map to the same cell


def test_no_provider_lookup_marks_error(store):
    repo = ExecutionRepository(store, "executions")
    svc = GenerationService(repo, Settings(), provider_lookup=None)
    ex = asyncio.run(svc.generate(_case(), _spec()))
    assert ex.status == ExecStatus.ERROR


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
