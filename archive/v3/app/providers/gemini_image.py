"""Gemini image provider — T2I / I2I via google.genai (Vertex ADC).

Ports v2 ``gemini_image_provider.py``. Produces image bytes which are uploaded
to GCS; the ``gs://`` URI becomes the ``media_uri``. Provider id is ``gemini``
(matches v2 ``image_pipeline`` ``side["provider"]``).

The real generate_content call + upload live in :meth:`GeminiImageProvider._call`.
Latency is measured in ``generate`` and reported in SECONDS.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from app.config import get_settings
from app.domain.models import Case, ExecStatus, GenerationResult, ModelSpec
from app.providers.base import register_cls


def _effective_params(case: Case, override: dict[str, Any] | None) -> dict[str, Any]:
    p = dict(case.params or {})
    if override:
        p.update(override)
    return p


def _norm_resolution(resolution: Any) -> str | None:
    r = str(resolution or "").strip().lower()
    if not r:
        return None
    if r in ("4k", "4096"):
        return "4K"
    if r in ("2k", "2048"):
        return "2K"
    return "1K"


def _extract_image(resp: Any) -> tuple[bytes | None, str | None]:
    for cand in (getattr(resp, "candidates", None) or []):
        content = getattr(cand, "content", None)
        for part in (getattr(content, "parts", None) or []):
            inline = getattr(part, "inline_data", None)
            if inline and getattr(inline, "data", None):
                return inline.data, (getattr(inline, "mime_type", None) or "image/png")
    return None, None


@register_cls("gemini")
class GeminiImageProvider:
    provider_id: str = "gemini"

    async def generate(self, case: Case, spec: ModelSpec,
                       params: dict[str, Any] | None = None) -> GenerationResult:
        p = _effective_params(case, params)
        t0 = time.perf_counter()
        try:
            out = await self._call(case, spec, p)
        except Exception as exc:
            return GenerationResult(status=ExecStatus.ERROR, model_id=spec.model_id,
                                    error=str(exc), latency_s=round(time.perf_counter() - t0, 3))
        latency = round(time.perf_counter() - t0, 3)
        media = out.get("media_uri")
        if not media:
            return GenerationResult(status=ExecStatus.ERROR, model_id=spec.model_id,
                                    error=out.get("error") or "model returned no image",
                                    latency_s=latency, raw=out.get("raw", {}))
        return GenerationResult(status=ExecStatus.SUCCESS, media_uri=media, latency_s=latency,
                                model_id=spec.model_id, raw=out.get("raw", {}))

    async def _call(self, case: Case, spec: ModelSpec, p: dict[str, Any]) -> dict[str, Any]:
        from google import genai
        from google.genai import types

        from app.infra.gcs import GcsClient

        settings = get_settings()
        contents: list[Any] = [case.prompt or ""]
        # I2I: first input asset supplied as an inline image part (omitted in the
        # stubbed path; wired in prod via download+from_bytes).

        ic_kwargs: dict[str, Any] = {}
        ar = str(p.get("aspect_ratio") or "").strip() or None
        res = _norm_resolution(p.get("resolution"))
        if ar:
            ic_kwargs["aspect_ratio"] = ar
        if res:
            ic_kwargs["image_size"] = res
        config = types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(**ic_kwargs) if ic_kwargs else None)

        def _run() -> tuple[bytes | None, str | None]:
            client = genai.Client(vertexai=True, project=settings.gcp_project_id,
                                  location=settings.image_location)
            resp = client.models.generate_content(
                model=spec.model_id, contents=contents, config=config)
            return _extract_image(resp)

        img_bytes, mime = await asyncio.to_thread(_run)
        if not img_bytes:
            return {"error": "model returned no image", "raw": {}}
        ext = {"image/jpeg": "jpg", "image/webp": "webp"}.get(mime or "", "png")
        gcs = GcsClient(settings.gcs_bucket_name)
        uri = gcs.upload_bytes(img_bytes, f"images/img_{int(time.time() * 1000)}.{ext}",
                               content_type=mime or "image/png")
        return {"media_uri": uri, "raw": {"mime_type": mime}}
