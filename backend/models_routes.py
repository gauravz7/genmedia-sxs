"""Model registry endpoints — /api/models.

Registering a model here is what makes its name usable in the intake API and in
the compose forms."""

from typing import Optional

from fastapi import (APIRouter, Depends)

from auth import require_admin
from registry import RegisteredModel, registry

router = APIRouter()


@router.get("/api/models")
async def get_models(modality: Optional[str] = None, active_only: bool = False):
    """All registered models. `modality` filters to video | image | tts — the
    registry now spans all three, so the video admin views pass it explicitly."""
    from model_resolver import modality_of
    out = list(registry.models.values())
    if modality:
        out = [m for m in out if modality_of(m) == modality]
    if active_only:
        out = [m for m in out if m.is_active]
    return out


@router.post("/api/models", dependencies=[Depends(require_admin)])
async def add_model(model: RegisteredModel):
    registry.add_model(model)
    return {"status": "success", "model": model}


@router.post("/api/models/{model_id}/toggle", dependencies=[Depends(require_admin)])
async def toggle_model(model_id: str):
    if registry.toggle_model(model_id):
        return {"status": "success", "is_active": registry.models[model_id].is_active}
    return {"status": "error", "message": "Model not found"}


@router.delete("/api/models/{model_id}", dependencies=[Depends(require_admin)])
async def delete_model(model_id: str):
    if model_id not in registry.models:
        return {"status": "error", "message": "Model not found"}
    # Builtin entries are re-seeded from models_builtin.json on every boot, so
    # deleting one would silently come back. Deactivate instead — the overlay
    # persists that and it's what the caller actually wants.
    if model_id in registry.builtin_ids:
        registry.models[model_id].is_active = False
        registry.save()
        return {"status": "success", "deactivated": True,
                "message": "Builtin model deactivated (cannot be deleted)."}
    del registry.models[model_id]
    registry.save()
    return {"status": "success"}
