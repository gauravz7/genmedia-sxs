"""MAI image provider — Microsoft MAI-Image-2.5 via FAL (T2I / I2I).

Ports v2 ``mai_image_provider.py``. Provider id ``mai`` (matches v2
``image_pipeline`` ``side["provider"]``). FAL returns a hosted image URL used
directly as ``media_uri``.

The real ``fal_client`` call is isolated in :meth:`MaiImageProvider._call`.
Latency is measured in ``generate`` and reported in SECONDS.
"""
from __future__ import annotations

import os
import time
from typing import Any

from app.config import get_settings
from app.domain.models import Case, ExecStatus, GenerationResult, ModelSpec
from app.providers.base import register_cls

_VALID_AR = {"auto", "1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3"}


def _effective_params(case: Case, override: dict[str, Any] | None) -> dict[str, Any]:
    p = dict(case.params or {})
    if override:
        p.update(override)
    return p


def _aspect(aspect_ratio: Any) -> str:
    ar = str(aspect_ratio or "").strip().lower()
    return ar if ar in _VALID_AR else "auto"


def _extract_image_url(result: dict[str, Any]) -> str | None:
    images = result.get("images")
    if isinstance(images, list) and images:
        first = images[0]
        if isinstance(first, dict):
            return first.get("url")
        if isinstance(first, str):
            return first
    if isinstance(result.get("image"), dict):
        return result["image"].get("url")
    return result.get("url")


@register_cls("mai")
class MaiImageProvider:
    provider_id: str = "mai"

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
                                    error=out.get("error") or "MAI returned no image URL",
                                    latency_s=latency, raw=out.get("raw", {}))
        return GenerationResult(status=ExecStatus.SUCCESS, media_uri=media, latency_s=latency,
                                model_id=spec.model_id, raw=out.get("raw", {}))

    async def _call(self, case: Case, spec: ModelSpec, p: dict[str, Any]) -> dict[str, Any]:
        import fal_client

        settings = get_settings()
        if settings.fal_key:
            os.environ.setdefault("FAL_KEY", settings.fal_key)
        args: dict[str, Any] = {
            "prompt": case.prompt or "",
            "aspect_ratio": _aspect(p.get("aspect_ratio")),
            "num_images": 1,
            "output_format": "png",
        }
        assets = list(case.input_assets or [])
        mode = (spec.type or case.mode or "t2i").lower()
        if mode == "i2i" and assets:
            args["image_urls"] = [assets[0]]
            slug = f"{spec.model_id}/edit"
        else:
            slug = spec.model_id
        result = await fal_client.subscribe_async(slug, arguments=args)
        url = _extract_image_url(result if isinstance(result, dict) else {})
        return {"media_uri": url, "raw": {"original_url": url}}
