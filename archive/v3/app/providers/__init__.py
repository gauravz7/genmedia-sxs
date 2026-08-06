"""Provider package — importing it registers all provider implementations.

Each submodule registers its ``Provider`` under the ``provider_id`` used in v2's
``models.json`` (video) / image & TTS pipelines. ``bootstrap()`` is the
idempotent registration entrypoint other agents import; the generation service
dispatches by ``spec.provider == provider_id`` via ``get_provider``.
"""
from __future__ import annotations

# Importing each module runs its ``@register_cls`` decorator, registering the
# provider in ``app.providers.base._REGISTRY``.
from app.providers import (  # noqa: F401
    elevenlabs,
    fal,
    gemini_image,
    gemini_tts,
    gpt_image,
    mai_image,
    omni,
    vertex,
)
from app.providers.base import get_provider, registered_providers  # noqa: F401

_BOOTSTRAPPED = False


def bootstrap() -> None:
    """Ensure all providers are imported/registered. Idempotent — safe to call
    repeatedly (registration happens once at module import)."""
    global _BOOTSTRAPPED
    _BOOTSTRAPPED = True


__all__ = ["bootstrap", "get_provider", "registered_providers"]
