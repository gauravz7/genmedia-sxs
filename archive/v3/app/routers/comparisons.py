"""Comparisons router — derived head-to-head + AI judge (pairwise).

A Comparison references two executions of the same case. ``/evaluate`` runs the
LLM-as-judge in pairwise mode and persists the verdict, which then feeds the
win-map and human/AI-agreement analytics.
"""
from __future__ import annotations

import hashlib
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.deps import (
    get_comparison_repo,
    get_evaluation_service,
    get_execution_repo,
)
from app.domain.models import Case, Comparison, Execution, Modality

router = APIRouter(prefix="/api/comparisons", tags=["comparisons"])

_ExecRepo = Depends(get_execution_repo)
_CompRepo = Depends(get_comparison_repo)
_EvalService = Depends(get_evaluation_service)
_CaseQ = Query(...)


class EvaluateRequest(BaseModel):
    execution_a: str
    execution_b: str


def _comparison_id(a: str, b: str) -> str:
    key = "|".join(sorted((a, b)))
    return "cmp_" + hashlib.sha256(key.encode()).hexdigest()[:20]


@router.post("/evaluate")
async def evaluate_pair(
    req: EvaluateRequest,
    exec_repo: Any = _ExecRepo,
    comp_repo: Any = _CompRepo,
    evaluator: Any = _EvalService,
) -> dict:
    da = exec_repo.get(req.execution_a)
    db = exec_repo.get(req.execution_b)
    if not da or not db:
        raise HTTPException(status_code=404, detail="Execution(s) not found")
    if da.get("case_id") != db.get("case_id"):
        raise HTTPException(status_code=400, detail="Executions are for different cases")

    exec_a = Execution.model_validate(da)
    exec_b = Execution.model_validate(db)
    case = Case(
        id=exec_a.case_id, prompt=exec_a.prompt,
        modality=exec_a.modality, mode=exec_a.mode,
        categories=exec_a.categories, language=exec_a.language,
        input_assets=exec_a.input_assets,
    )
    verdict = await evaluator.evaluate_pairwise(case, exec_a, exec_b)

    comp = Comparison(
        id=_comparison_id(exec_a.id, exec_b.id),
        case_id=exec_a.case_id,
        execution_a=exec_a.id,
        execution_b=exec_b.id,
        modality=exec_a.modality or Modality.T2I,
        ai_verdict={
            "winner_execution": verdict.winner_execution,
            "per_execution": verdict.per_execution,
            "model": verdict.model,
        },
    )
    comp_repo.set(comp.id, comp.model_dump(mode="json"))
    return comp.model_dump(mode="json")


@router.get("")
def list_comparisons(
    case_id: str = _CaseQ,
    comp_repo: Any = _CompRepo,
) -> list[dict]:
    return comp_repo.by_case(case_id)
