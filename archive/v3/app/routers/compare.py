"""Compare router — the blind human-SxS voting surface.

``/api/compare/pair`` auto-serves a randomized, model-hidden matchup; the voter
casts through ``/api/votes`` (which requires an ldap and dedups). Model identities
are disclosed only by ``/api/compare/reveal`` after the vote, and each side's
media streams through ``/api/compare/media`` so the ``gs://`` path (which embeds
the provider) never reaches the browser.
"""
from __future__ import annotations

import mimetypes
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.deps import get_compare_service, get_gcs_client

router = APIRouter(prefix="/api/compare", tags=["compare"])

# Module-level dependency singletons (avoid function calls in arg defaults).
_Compare = Depends(get_compare_service)
_Gcs = Depends(get_gcs_client)
_ModalityQ = Query(default=None)
_TagQ = Query(default=None)
_CaseQ = Query(default=None)
_ExecQ = Query(...)
_ExecAQ = Query(...)
_ExecBQ = Query(...)


@router.get("/pair")
def next_pair(
    modality: str | None = _ModalityQ,
    tag: str | None = _TagQ,
    case_id: str | None = _CaseQ,
    service: Any = _Compare,
) -> Any:
    """Serve one blind matchup (opaque execution ids + blind media refs + shared
    prompt, no model identity). 404 when no eligible case exists."""
    pair = service.pick_pair(modality=modality, tag=tag, case_id=case_id)
    if pair is None:
        raise HTTPException(status_code=404, detail="No eligible pair available")
    return pair


@router.get("/reveal")
def reveal(
    execution_a: str = _ExecAQ,
    execution_b: str = _ExecBQ,
    service: Any = _Compare,
) -> Any:
    """Disclose the two sides' model identities — call after voting."""
    return service.reveal(execution_a, execution_b)


@router.get("/media")
def blind_media(
    execution_id: str = _ExecQ,
    service: Any = _Compare,
    gcs: Any = _Gcs,
) -> Any:
    """Stream a blind side's bytes without exposing its ``gs://`` path."""
    uri = service.media_uri_of(execution_id)
    if not uri or not uri.startswith("gs://"):
        raise HTTPException(status_code=404, detail="Media not found")
    try:
        data = gcs.download_bytes(uri)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Object not found") from exc
    except Exception as exc:  # noqa: BLE001 - surface storage errors as 502
        raise HTTPException(status_code=502, detail=f"Media fetch failed: {exc}") from exc
    content_type = mimetypes.guess_type(uri)[0] or "application/octet-stream"
    return Response(content=data, media_type=content_type,
                    headers={"Cache-Control": "private, max-age=3600"})
