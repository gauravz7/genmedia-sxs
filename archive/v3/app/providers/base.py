"""Provider interface + registry (Phase 4 contract).

Every model backend implements ``Provider.generate`` returning a normalized
``GenerationResult`` (latency in seconds). Providers register themselves by the
``provider`` id used in the model registry (matches v2 ``models.json``), so the
generation service dispatches by lookup instead of hardcoded branches
(v2's ``generate_seedance`` / ``generate_omni`` / ``_gen_side``).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from app.domain.models import Case, GenerationResult, ModelSpec


@runtime_checkable
class Provider(Protocol):
    provider_id: str

    async def generate(self, case: Case, spec: ModelSpec,
                       params: dict[str, Any] | None = None) -> GenerationResult:
        ...


_REGISTRY: dict[str, Provider] = {}


def register(provider: Provider) -> Provider:
    """Register a provider instance under its ``provider_id``."""
    _REGISTRY[provider.provider_id] = provider
    return provider


def register_cls(provider_id: str) -> Callable[[type], type]:
    """Class decorator: instantiate and register a Provider subclass."""
    def _wrap(cls: type) -> type:
        inst = cls()
        inst.provider_id = provider_id
        _REGISTRY[provider_id] = inst  # type: ignore[assignment]
        return cls
    return _wrap


def get_provider(provider_id: str) -> Provider:
    if provider_id not in _REGISTRY:
        raise KeyError(f"No provider registered for '{provider_id}'. "
                       f"Known: {sorted(_REGISTRY)}")
    return _REGISTRY[provider_id]


def registered_providers() -> list[str]:
    return sorted(_REGISTRY)


def clear_registry() -> None:  # test helper
    _REGISTRY.clear()
