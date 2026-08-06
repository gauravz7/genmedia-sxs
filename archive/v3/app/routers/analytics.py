"""Analytics router — win-map, human/AI agreement, and Elo/Bradley-Terry
rankings, all served by :class:`AnalyticsService`.

The service's method surface is owned by a sibling agent; endpoints resolve the
method defensively (``getattr``) so a not-yet-implemented metric returns a clean
501 instead of a 500, and the app still boots if the service module is absent.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.deps import get_analytics_service

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

# Module-level dependency singletons (avoid function calls in arg defaults).
_Service = Depends(get_analytics_service)
_SuiteQ = Query(default=None)
_ModalityQ = Query(default=None)
_MethodQ = Query(default="bradley_terry")
_MinNQ = Query(default=1, ge=1)
_TagQ = Query(default=None)
_LdapQ = Query(default=None)
_LdapReqQ = Query(...)


@router.get("/winmap")
def win_map(
    min_n: int = _MinNQ,
    service: Any = _Service,
) -> Any:
    """Google-vs-competitor win-rate from the AI judge, with 95% Wilson CIs."""
    return service.win_map(min_n=min_n)


@router.get("/latency")
def latency(service: Any = _Service) -> Any:
    """Average successful-generation latency per (modality, model), in seconds."""
    return service.latency()


@router.get("/stats")
def stats(
    modality: str | None = _ModalityQ,
    tag: str | None = _TagQ,
    ldap: str | None = _LdapQ,
    service: Any = _Service,
) -> Any:
    """Win-rate SKU leaderboard, per-metric radar averages, and by-tag matrix
    from human votes + the AI judge. Optional ``modality``/``tag``/``ldap``."""
    return service.stats(modality=modality, tag=tag, ldap=ldap)


@router.get("/leaderboard")
def leaderboard(service: Any = _Service) -> Any:
    """Top voters overall + per modality group, excluding suspected blind voters."""
    return service.voter_leaderboard()


@router.get("/votes/count")
def votes_count(
    ldap: str = _LdapReqQ,
    service: Any = _Service,
) -> Any:
    """Votes cast by ``ldap`` and whether they've cleared the ≥10 analytics gate."""
    return service.vote_count(ldap=ldap)


@router.get("/agreement")
def agreement(service: Any = _Service) -> Any:
    """Human/AI agreement over pairs that have both a vote and an AI verdict."""
    return service.agreement()


@router.get("/rankings")
def rankings(
    suite_id: str | None = _SuiteQ,
    modality: str | None = _ModalityQ,
    method: str = _MethodQ,
    service: Any = _Service,
) -> Any:
    """Global model ranking: ``method`` = ``bradley_terry`` (default) or ``elo``."""
    return service.rankings(method=method, suite_id=suite_id, modality=modality)
