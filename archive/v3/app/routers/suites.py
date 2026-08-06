"""Suites router — CRUD for prompt suites via :class:`SuiteService`.

The service method surface is owned by a sibling agent; endpoints resolve methods
defensively so an unimplemented operation returns a clean 501 rather than a 500,
and the app still boots if the service module is absent.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_suite_service
from app.domain.models import Suite

router = APIRouter(prefix="/api/suites", tags=["suites"])

# Module-level dependency singleton (avoid function calls in arg defaults).
_Service = Depends(get_suite_service)


def _resolve(service: Any, names: tuple[str, ...]) -> Any:
    for name in names:
        fn = getattr(service, name, None)
        if callable(fn):
            return fn
    raise HTTPException(status_code=501, detail=f"Suite op not implemented: {names[0]}")


@router.get("")
def list_suites(service: Any = _Service) -> Any:
    return _resolve(service, ("list_suites", "list_all", "list"))()


@router.get("/{suite_id}")
def get_suite(suite_id: str, service: Any = _Service) -> Any:
    result = _resolve(service, ("get_suite", "get"))(suite_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Suite not found")
    return result


@router.post("")
def create_suite(suite: Suite, service: Any = _Service) -> Any:
    return _resolve(service, ("create_suite", "create", "save", "upsert"))(suite.model_dump())


@router.put("/{suite_id}")
def update_suite(
    suite_id: str, suite: Suite, service: Any = _Service
) -> Any:
    # SuiteRepository.set is upsert semantics — route update through create.
    data = suite.model_dump()
    data["id"] = suite_id
    return _resolve(service, ("update_suite", "update", "create", "save", "upsert"))(data)


@router.delete("/{suite_id}")
def delete_suite(suite_id: str, service: Any = _Service) -> Any:
    _resolve(service, ("delete_suite", "delete"))(suite_id)
    return {"status": "ok", "id": suite_id}
