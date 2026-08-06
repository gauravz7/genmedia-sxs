"""Votes router — human (or AI) verdicts referencing two executions.

A Vote is a derived relation over two Execution ids of the same case; it never
triggers generation. Ids are content-independent, so we mint one if the client
omits it.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.deps import get_vote_repo
from app.domain.models import Vote, VoteSource

# Ballot values that are not a real, attributable voter identity.
_ANON_LDAPS = {"", "anonymous", "global"}

router = APIRouter(prefix="/api/votes", tags=["votes"])

# Module-level dependency singletons (avoid function calls in arg defaults).
_VoteRepo = Depends(get_vote_repo)
_CaseIdQ = Query(...)


class VoteRequest(BaseModel):
    case_id: str
    execution_a: str
    execution_b: str
    winner_execution: str | None = None
    scores: dict[str, int] = Field(default_factory=dict)
    justification: str = ""
    source: VoteSource = VoteSource.HUMAN
    ldap: str = "anonymous"


@router.post("")
def cast_vote(
    req: VoteRequest,
    vote_repo: Any = _VoteRepo,
) -> dict:
    """Cast a vote. Human votes must carry a real ``ldap`` (analytics + the
    anti-gaming leaderboard key on it). One vote per (case, pair, voter): a
    re-vote for the same matchup overwrites the prior one rather than stuffing
    the ballot, so an honest mind-change is allowed but duplicates are not."""
    ldap = (req.ldap or "").strip()
    if req.source == VoteSource.HUMAN and ldap.lower() in _ANON_LDAPS:
        raise HTTPException(
            status_code=400,
            detail="A human vote requires a non-anonymous 'ldap' voter id.",
        )

    # Dedup on (case, unordered pair, voter): reuse the existing id → overwrite.
    pair = {req.execution_a, req.execution_b}
    existing = next(
        (v for v in vote_repo.by_case(req.case_id)
         if (v.get("ldap") or "").strip() == ldap
         and {v.get("execution_a"), v.get("execution_b")} == pair),
        None,
    )
    vote_id = existing["id"] if existing else f"vote_{uuid.uuid4().hex[:16]}"

    vote = Vote(
        id=vote_id,
        case_id=req.case_id,
        execution_a=req.execution_a,
        execution_b=req.execution_b,
        winner_execution=req.winner_execution,
        scores=req.scores,
        justification=req.justification,
        source=req.source,
        ldap=ldap or "anonymous",
        timestamp=time.time(),
    )
    vote_repo.add(vote.model_dump(mode="json"))
    return {"status": "ok", "id": vote.id, "deduped": existing is not None}


@router.get("")
def list_votes(
    case_id: str = _CaseIdQ,
    vote_repo: Any = _VoteRepo,
) -> list[dict]:
    return vote_repo.by_case(case_id)
