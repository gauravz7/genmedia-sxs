"""Media router — authenticated proxy for ``gs://`` objects.

By default it STREAMS the object bytes through the backend (works with plain
ADC, which only needs read access) — mirroring the v2 ``/api/media`` proxy so
raw ``gs://`` URIs are never exposed to the client. Pass ``?signed=true`` to get
a V4 signed URL instead (requires a signing-capable service-account credential).

SSRF guard: only Google Cloud Storage ``gs://`` URIs are accepted.
"""
from __future__ import annotations

import mimetypes
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.deps import get_gcs_client

router = APIRouter(prefix="/api/media", tags=["media"])

# Module-level dependency singletons (avoid function calls in arg defaults).
_UriQ = Query(..., description="A gs:// object URI")
_TtlQ = Query(default=3600, ge=1, le=604800)
_SignedQ = Query(default=False)
_Gcs = Depends(get_gcs_client)


def _normalize(uri: str) -> str:
    fixed = uri
    if fixed.startswith("gs:/") and not fixed.startswith("gs://"):
        fixed = "gs://" + fixed[len("gs:/"):]
    if not fixed.startswith("gs://"):
        raise HTTPException(status_code=400, detail="Only gs:// URIs are allowed")
    return fixed


@router.get("")
def get_media(
    uri: str = _UriQ,
    signed: bool = _SignedQ,
    ttl_seconds: int = _TtlQ,
    gcs: Any = _Gcs,
) -> Any:
    fixed = _normalize(uri)

    if signed:
        try:
            url = gcs.signed_url(fixed, ttl_seconds=ttl_seconds)
        except (ValueError, AttributeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"url": url, "uri": fixed, "ttl_seconds": ttl_seconds}

    # Default: stream the bytes through the proxy (ADC-friendly).
    try:
        data = gcs.download_bytes(fixed)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Object not found") from exc
    except Exception as exc:  # noqa: BLE001 - surface storage errors as 502
        raise HTTPException(status_code=502, detail=f"Media fetch failed: {exc}") from exc

    content_type = mimetypes.guess_type(fixed)[0] or "application/octet-stream"
    return Response(content=data, media_type=content_type,
                    headers={"Cache-Control": "private, max-age=3600"})
