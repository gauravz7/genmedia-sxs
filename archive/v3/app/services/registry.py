"""Model registry — reads the ``models.json`` file (id -> ModelSpec fields).

v2 kept an admin-mutable ``models.json`` keyed by model id. v3 reads the same
shape into :class:`ModelSpec` objects so the UI can offer a spec picker and the
generation service can dispatch by ``provider``. Read-only for now.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.config import Settings
from app.domain.models import ModelSpec


class ModelRegistry:
    def __init__(self, settings: Settings) -> None:
        self._path = Path(settings.models_path)

    def _raw(self) -> dict[str, dict]:
        if not self._path.exists():
            return {}
        data = json.loads(self._path.read_text())
        return data if isinstance(data, dict) else {}

    def list(self, *, active_only: bool = False, type_: str | None = None,
             modality: str | None = None) -> list[ModelSpec]:
        specs: list[ModelSpec] = []
        for key, entry in self._raw().items():
            e = dict(entry)
            e.setdefault("id", key)
            e.setdefault("model_version", "v1")
            try:
                spec = ModelSpec.model_validate(e)
            except Exception:
                continue
            if active_only and not spec.is_active:
                continue
            if type_ and spec.type != type_:
                continue
            if modality and spec.type != modality:
                continue
            specs.append(spec)
        return specs

    def get(self, model_id: str) -> ModelSpec | None:
        raw = self._raw()
        entry = raw.get(model_id)
        if entry is None:
            for key, e in raw.items():
                if e.get("id") == model_id or key == model_id:
                    entry = e
                    break
        if entry is None:
            return None
        e = dict(entry)
        e.setdefault("id", model_id)
        e.setdefault("model_version", "v1")
        return ModelSpec.model_validate(e)
