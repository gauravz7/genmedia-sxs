"""The model registry — one registry across video, image and TTS.

Split out of `main.py`; `main` re-exports `registry`, `RegisteredModel` and
`PROVIDER_TRANSPORT` because `model_resolver` and `tts_pipeline` reach for them
as `main.<name>`.
"""

import json
import os
from typing import Dict, List, Optional

from pydantic import BaseModel, model_validator


# Transport is derived from the provider, not chosen per model: every Google
# model goes through Vertex AI / GCP, every non-Google model through FAL.
PROVIDER_TRANSPORT = {
    "vertex": "vertex",       # Veo
    "omni": "vertex",         # Gemini Omni
    "gemini": "vertex",       # Gemini image
    "gemini_tts": "vertex",   # Gemini TTS
    "fal": "fal",             # Kling / Seedance / Grok
    "gpt": "fal",             # GPT-image via FAL
    "mai": "fal",             # MAI-Image via FAL
    "elevenlabs": "fal",      # ElevenLabs via FAL
}


class RegisteredModel(BaseModel):
    id: str
    name: str
    provider: str       # dispatch key — see PROVIDER_TRANSPORT for the full list
    model_id: str
    type: str = "t2v"   # 't2v', 'i2v', 'r2v' (video) | 't2i' (image) | 'tts'
    is_active: bool = True
    quality: Optional[str] = None    # GPT-image tier: low | medium | high
    transport: Optional[str] = None  # 'vertex' | 'fal' — derived from provider

    @model_validator(mode="after")
    def _derive_transport(self):
        expected = PROVIDER_TRANSPORT.get(self.provider)
        if expected is None:
            raise ValueError(
                f"Unknown provider '{self.provider}' for model '{self.id}'. "
                f"Known providers: {', '.join(sorted(PROVIDER_TRANSPORT))}"
            )
        # Always derive — a stale/hand-edited transport must not win over the rule.
        self.transport = expected
        return self


class RegistryManager:
    """The model registry.

    Reads two files, both relative to the backend working directory:
      - `models_builtin.json` — committed seed of the models the pipelines ship
        with (image + TTS engines, whose ids must match the `engine` strings
        written into job docs). Guarantees the registry is never empty.
      - `models.json` — the mutable overlay written by the admin API. Gitignored,
        and on Cloud Run it lives on the container's ephemeral disk, so entries
        added at runtime are lost when the instance recycles. Anything that must
        survive a restart belongs in the builtin seed.
    Overlay entries win on id collision.
    """

    def __init__(self, file_path="models.json", builtin_path="models_builtin.json"):
        self.file_path = file_path
        self.builtin_path = builtin_path
        self.builtin_ids: set = set()
        self.models: Dict[str, RegisteredModel] = self._load()

    def _read(self, path: str) -> Dict[str, "RegisteredModel"]:
        if not os.path.exists(path):
            return {}
        out: Dict[str, RegisteredModel] = {}
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except Exception as e:
            print(f"Error loading {path}: {e}")
            return {}
        for k, v in (data or {}).items():
            try:
                out[k] = RegisteredModel(**v)
            except Exception as e:
                # One bad entry must not take down the whole registry.
                print(f"Skipping invalid model '{k}' in {path}: {e}")
        return out

    def _load(self):
        builtin = self._read(self.builtin_path)
        self.builtin_ids = set(builtin)
        models = builtin
        models.update(self._read(self.file_path))
        if not models:
            return {"veo": RegisteredModel(id="veo", name="Veo 2.0", provider="vertex", model_id="veo-2.0-generate-001", type="i2v")}
        return models

    def save(self):
        with open(self.file_path, "w") as f:
            json.dump({k: v.dict() for k, v in self.models.items()}, f, indent=2)

    def add_model(self, model: RegisteredModel):
        self.models[model.id] = model
        self.save()

    def toggle_model(self, model_id: str):
        if model_id in self.models:
            self.models[model_id].is_active = not self.models[model_id].is_active
            self.save()
            return True
        return False

    def get_active_models(self) -> List[RegisteredModel]:
        return [m for m in self.models.values() if m.is_active]


# The one registry instance the whole app shares.
registry = RegistryManager()
