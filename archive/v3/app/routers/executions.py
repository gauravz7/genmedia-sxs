"""Execution router — the execution-centric core surface.

An Execution is the atomic, cached ``(case, model, params)`` primitive. POST here
requests generation of a single case×model; the :class:`GenerationService`
enforces the no-rerun guarantee, so re-POSTing the same request returns the same
execution id without regenerating.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.deps import get_execution_repo, get_generation_service, get_ingestion_service
from app.domain.models import Case, Execution, ModelSpec

router = APIRouter(prefix="/api/executions", tags=["executions"])

# Module-level dependency singletons (avoid function calls in arg defaults).
_ExecRepo = Depends(get_execution_repo)
_GenService = Depends(get_generation_service)
_IngestService = Depends(get_ingestion_service)
_SuiteQ = Query(default=None)
_CaseQ = Query(default=None)


class GenerateRequest(BaseModel):
    case: Case
    spec: ModelSpec
    params: dict[str, Any] | None = Field(default=None)


class IngestRequest(BaseModel):
    case: Case
    spec: ModelSpec
    media_uri: str
    params: dict[str, Any] | None = Field(default=None)
    metadata: dict[str, Any] | None = Field(default=None)


class BatchIngestRequest(BaseModel):
    """Bulk BYOO envelope — a JSON array of ingest cells under ``items``.

    Each item is the exact same schema as a single ``/ingest`` body (Case +
    ModelSpec + media_uri), so the two endpoints share one standardized
    vocabulary. Items are typed ``dict`` (not ``IngestRequest``) so that a
    single malformed row is reported per-row in ``errors`` rather than
    422-ing the whole batch. Mirrors the array shape of ``/api/{modality}/jobs``."""

    items: list[dict[str, Any]] = Field(default_factory=list)


@router.post("")
async def request_execution(
    req: GenerateRequest,
    gen: Any = _GenService,
) -> Execution:
    """Request generation of one case×model. Honors the no-rerun guarantee:
    identical (case, model, params) always resolves to the same execution."""
    return await gen.generate(req.case, req.spec, params=req.params)


@router.post("/ingest")
def ingest_execution(
    req: IngestRequest,
    ingest: Any = _IngestService,
) -> Execution:
    """BYOO — register a pre-generated output as an Execution (source=ingested).
    Same content-addressed identity, so re-ingesting the same cell is deduped."""
    return ingest.ingest(req.case, req.spec, req.media_uri,
                         params=req.params, metadata=req.metadata)


@router.post("/ingest/batch")
def ingest_batch(
    req: BatchIngestRequest,
    ingest: Any = _IngestService,
) -> dict:
    """Bulk BYOO — register an array of pre-generated outputs in one call.
    Each row is content-addressed/deduped like ``/ingest``; a row that fails
    validation OR registration is reported in ``errors`` without aborting the
    rest of the batch."""
    from pydantic import ValidationError

    from app.services.ingestion import BatchItem

    items: list[BatchItem] = []
    row_errors: list[dict[str, Any]] = []
    for i, raw in enumerate(req.items):
        try:
            it = IngestRequest.model_validate(raw)
            items.append(
                BatchItem(it.case, it.spec, it.media_uri,
                          params=it.params, metadata=it.metadata)
            )
        except ValidationError as exc:
            row_errors.append({"index": i, "error": exc.errors(include_url=False)})

    result = ingest.ingest_batch(items)
    # Merge schema-validation failures with ingest-time failures.
    result["errors"] = row_errors + result.get("errors", [])
    result["received"] = len(req.items)
    return result


@router.get("/{execution_id}")
def get_execution(
    execution_id: str,
    exec_repo: Any = _ExecRepo,
) -> dict:
    doc = exec_repo.get(execution_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    return doc


@router.get("")
def list_executions(
    suite_id: str | None = _SuiteQ,
    case_id: str | None = _CaseQ,
    exec_repo: Any = _ExecRepo,
) -> list[dict]:
    if case_id:
        return exec_repo.by_case(case_id)
    if suite_id:
        return exec_repo.by_suite(suite_id)
    return []
