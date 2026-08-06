"""Video (t2v/i2v/r2v) modality router.

Job submission is execution-centric: a job is suite × models materialized into
Executions (deduped by the generation service), optionally evaluated in
``absolute`` / ``pairwise`` / ``both`` mode. Mirrors the v2 ``/api/sxs/*``
surface at a high level without reproducing its pair-centric internals.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.deps import get_execution_repo, get_generation_service
from app.domain.models import Case, EvalMode, Modality, ModelSpec

router = APIRouter(prefix="/api/video", tags=["video"])

MODALITIES = {Modality.T2V.value, Modality.I2V.value, Modality.R2V.value}

# Module-level dependency singletons (avoid function calls in arg defaults).
_GenService = Depends(get_generation_service)
_ExecRepo = Depends(get_execution_repo)
_SuiteIdQ = Query(...)


class JobRequest(BaseModel):
    suite_id: str | None = None
    cases: list[Case] = Field(default_factory=list)
    specs: list[ModelSpec] = Field(default_factory=list)
    eval_mode: EvalMode = EvalMode.BOTH


@router.post("/jobs")
async def submit_job(
    req: JobRequest,
    gen: Any = _GenService,
) -> dict:
    execution_ids: list[str] = []
    for case in req.cases:
        for spec in req.specs:
            execution = await gen.generate(case, spec)
            execution_ids.append(execution.id)
    return {
        "modality": "video",
        "suite_id": req.suite_id,
        "eval_mode": req.eval_mode.value,
        "count": len(execution_ids),
        "executions": execution_ids,
    }


@router.get("/jobs")
def list_jobs(
    suite_id: str = _SuiteIdQ,
    exec_repo: Any = _ExecRepo,
) -> dict:
    docs = [d for d in exec_repo.by_suite(suite_id) if d.get("modality") in MODALITIES]
    return {"modality": "video", "suite_id": suite_id, "executions": docs}


@router.get("/results")
def get_results(
    suite_id: str = _SuiteIdQ,
    exec_repo: Any = _ExecRepo,
) -> dict:
    docs = [d for d in exec_repo.by_suite(suite_id) if d.get("modality") in MODALITIES]
    return {
        "modality": "video",
        "suite_id": suite_id,
        "count": len(docs),
        "results": docs,
    }
