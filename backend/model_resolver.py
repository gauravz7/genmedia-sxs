"""Shared model-name gate for the intake APIs.

Callers of `/api/{sxs,image,tts}/prompts` name the models they want run. This
module is the single place that answers "is that model registered and active?"
and translates a registry entry into whatever shape the target pipeline needs:

  - video  → `RegisteredModel` objects, consumed as dicts by
             `sxs_pipeline.create_admin_job` / `generate_for_model`
  - image  → side dicts `{engine, provider, model, quality}`, the shape
             `image_pipeline._gen_side` dispatches on
  - tts    → engine ids, matching `tts_pipeline.ENGINE_*`

The registry itself lives in `main.RegistryManager` and is imported lazily
inside the functions: `main` imports this module's router at the bottom of the
file, so a module-level import would be circular. By the time any of these
functions run, `main.registry` is fully constructed.
"""

from typing import Dict, List, Optional

from fastapi import HTTPException

# Registry `type` → intake modality. Video is the only many-to-one mapping.
MODALITY_BY_TYPE: Dict[str, str] = {
    "t2v": "video",
    "i2v": "video",
    "r2v": "video",
    "t2i": "image",
    "i2i": "image",
    "tts": "tts",
}

# Modalities whose job doc is strictly two-sided (results keyed "A"/"B").
TWO_SIDED = ("image", "tts")

# Providers each pipeline knows how to dispatch to.
_IMAGE_PROVIDERS = ("gemini", "gpt", "mai")
_TTS_PROVIDERS = ("gemini_tts", "elevenlabs")
_VIDEO_PROVIDERS = ("vertex", "fal", "omni")

_PROVIDERS_BY_MODALITY = {
    "video": _VIDEO_PROVIDERS,
    "image": _IMAGE_PROVIDERS,
    "tts": _TTS_PROVIDERS,
}


def _registry():
    import main  # lazy — see module docstring
    return main.registry


def modality_of(spec) -> Optional[str]:
    """The intake modality a registered model belongs to, or None if its `type`
    is unrecognized."""
    return MODALITY_BY_TYPE.get((getattr(spec, "type", "") or "").strip().lower())


def list_models(modality: Optional[str] = None, active_only: bool = True) -> List[dict]:
    """Registry view for the intake docs / admin UI, optionally scoped to one
    modality."""
    out = []
    for spec in _registry().models.values():
        m = modality_of(spec)
        if modality and m != modality:
            continue
        if active_only and not spec.is_active:
            continue
        out.append({
            "id": spec.id, "name": spec.name, "modality": m, "type": spec.type,
            "provider": spec.provider, "transport": spec.transport,
            "quality": spec.quality, "is_active": spec.is_active,
        })
    return sorted(out, key=lambda m: (m["modality"] or "", m["id"]))


def resolve_models(modality: str, names: List[str]) -> List:
    """Look up model ids for a modality. Raises 400 naming every id that is
    unknown, inactive, or belongs to a different modality — all of them at once,
    so a caller fixing a batch sees every problem in one response.
    """
    if not names:
        raise HTTPException(status_code=400, detail="No models specified.")

    known = _registry().models
    specs, problems = [], []
    for raw in names:
        name = (raw or "").strip()
        if not name:
            problems.append("(empty model name)")
            continue
        spec = known.get(name)
        if spec is None:
            problems.append(f"'{name}' is not a registered model")
            continue
        actual = modality_of(spec)
        if actual != modality:
            problems.append(
                f"'{name}' is a {actual or 'unknown'} model, not {modality}"
            )
            continue
        if not spec.is_active:
            problems.append(f"'{name}' is registered but not active")
            continue
        if spec.provider not in _PROVIDERS_BY_MODALITY.get(modality, ()):
            problems.append(
                f"'{name}' has provider '{spec.provider}', which the {modality} "
                "pipeline cannot dispatch to"
            )
            continue
        specs.append(spec)

    if problems:
        available = [m["id"] for m in list_models(modality)]
        raise HTTPException(status_code=400, detail={
            "error": "Unusable model(s) requested.",
            "problems": problems,
            "available": available,
        })

    ids = [s.id for s in specs]
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=400, detail=f"Duplicate model(s): {ids}")
    if modality in TWO_SIDED and len(specs) != 2:
        raise HTTPException(
            status_code=400,
            detail=(f"{modality} duels are two-sided: pass exactly 2 models, "
                    f"got {len(specs)}."),
        )
    return specs


def require_video_type(specs: List, case_type: str) -> None:
    """Video models are type-specific (t2v/i2v/r2v). Reject a batch whose models
    don't match what the case actually is."""
    wrong = [f"{s.id} ({s.type})" for s in specs if s.type != case_type]
    if wrong:
        raise HTTPException(
            status_code=400,
            detail=(f"Case is '{case_type}' but these models are not: "
                    + ", ".join(wrong)),
        )


def image_side_from_spec(spec) -> dict:
    """Registry entry → the side dict `image_pipeline._gen_side` dispatches on.

    `engine` is the stable identity written into job docs, side_map, and
    analytics, so it must equal the registry id (which in turn matches the
    strings `image_pipeline._gemini_side` / `_gpt_side` / `_mai_side` produce).
    """
    return {
        "engine": spec.id,
        "provider": spec.provider,
        "model": spec.model_id,
        "quality": spec.quality,
    }


def image_sides_from_specs(specs: List) -> tuple:
    return image_side_from_spec(specs[0]), image_side_from_spec(specs[1])


def tts_engines_from_specs(specs: List) -> List[str]:
    return [s.id for s in specs]
