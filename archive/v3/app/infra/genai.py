"""google-genai client factory (Agent 1 / Phase 2 infra).

``get_genai_client`` returns a ``google.genai`` ``Client`` configured for Vertex
AI (``vertexai=True``). The ``google.genai`` import lives inside the function so
that importing this module — and therefore the whole app in tests — never
requires the package or GCP credentials.
"""
from __future__ import annotations

from typing import Any, Protocol


class GenaiClient(Protocol):
    """Structural type for the bits of ``google.genai.Client`` we depend on.

    Kept intentionally loose (``models`` surface) so evaluators can type against
    it and tests can substitute a fake without importing ``google.genai``.
    """

    models: Any


def get_genai_client(project: str, location: str) -> GenaiClient:
    """Return a Vertex-configured ``google.genai`` client.

    Lazily imports ``google.genai`` so the module is import-safe offline.
    """
    from google import genai

    return genai.Client(vertexai=True, project=project, location=location)
