"""Model registry router — lets the UI list available models to run."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.config import Settings
from app.deps import get_settings_dep

router = APIRouter(prefix="/api/models", tags=["models"])

_SettingsDep = Depends(get_settings_dep)
_ActiveQ = Query(default=False)
_TypeQ = Query(default=None)


def _registry(settings: Settings) -> Any:
    from app.services.registry import ModelRegistry

    return ModelRegistry(settings)


@router.get("")
def list_models(
    active: bool = _ActiveQ,
    type: str | None = _TypeQ,  # noqa: A002 - matches query param name
    settings: Settings = _SettingsDep,
) -> list[dict]:
    specs = _registry(settings).list(active_only=active, type_=type)
    return [s.model_dump() for s in specs]


@router.get("/{model_id}")
def get_model(model_id: str, settings: Settings = _SettingsDep) -> dict:
    spec = _registry(settings).get(model_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="Model not found")
    return spec.model_dump()
