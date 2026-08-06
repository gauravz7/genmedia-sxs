"""Tests for IngestionService (BYOO) — ingest + dedup."""
from __future__ import annotations

from app.config import Settings
from app.domain.models import Case, ExecStatus, Modality, ModelSpec, execution_id
from app.infra.repositories import ExecutionRepository
from app.services.ingestion import BatchItem, IngestionService


def _svc(store) -> IngestionService:
    return IngestionService(ExecutionRepository(store, "executions"), Settings())


def _case(**kw) -> Case:
    base = dict(id="c1", prompt="A red fox in snow", modality=Modality.T2I, mode="t2i")
    base.update(kw)
    return Case(**base)


def _spec(**kw) -> ModelSpec:
    base = dict(id="m1", provider="ext", model_id="imagen-4.0", model_version="v1")
    base.update(kw)
    return ModelSpec(**base)


def test_ingest_creates_ingested_success_execution(store):
    svc = _svc(store)
    ex = svc.ingest(_case(), _spec(), "gs://b/o.png", metadata={"source_sheet": "row3"})
    assert ex.id == execution_id(_case(), _spec())
    assert ex.source == "ingested"
    assert ex.status == ExecStatus.SUCCESS
    assert ex.media_uri == "gs://b/o.png"
    assert ex.metadata["source_sheet"] == "row3"


def test_reingest_same_cell_dedups(store):
    svc = _svc(store)
    a = svc.ingest(_case(), _spec(), "gs://b/first.png")
    b = svc.ingest(_case(), _spec(), "gs://b/SECOND.png")  # same cell, new uri ignored
    assert a.id == b.id
    assert b.media_uri == "gs://b/first.png"  # original wins; no overwrite


def test_new_model_version_is_new_cell(store):
    svc = _svc(store)
    a = svc.ingest(_case(), _spec(model_version="v1"), "gs://b/a.png")
    b = svc.ingest(_case(), _spec(model_version="v2"), "gs://b/b.png")
    assert a.id != b.id
    assert b.media_uri == "gs://b/b.png"


def test_ingest_batch_dedups_and_reports(store):
    svc = _svc(store)
    items = [
        BatchItem(_case(), _spec(model_id="imagen-4.0"), "gs://b/a.png"),
        # exact same cell as the first row -> dedups to one stored execution
        BatchItem(_case(), _spec(model_id="imagen-4.0"), "gs://b/dup.png"),
        BatchItem(_case(), _spec(model_id="gpt-image-2"), "gs://b/b.png"),
    ]
    res = svc.ingest_batch(items)
    assert res["count"] == 3            # one result row echoed per input item
    assert res["errors"] == []
    # but only two DISTINCT executions are actually stored
    stored = svc.exec_repo.by_case("c1")
    assert len({e["id"] for e in stored}) == 2


def test_ingest_pair(store):
    svc = _svc(store)
    a, b = svc.ingest_pair(
        _case(),
        _spec(model_id="imagen-4.0"), "gs://b/a.png",
        _spec(model_id="gpt-image-2"), "gs://b/b.png",
    )
    assert a.id != b.id
    assert a.media_uri == "gs://b/a.png"
    assert b.media_uri == "gs://b/b.png"
    assert a.source == b.source == "ingested"
