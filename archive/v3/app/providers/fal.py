"""FAL provider — video generation via fal.ai (ports v2 ``fal_provider.py``).

Covers Seedance / Kling / Grok families. Request shaping (aspect ratio,
duration, i2v/r2v inputs) mirrors v2's ``generate_with_fal``. FAL returns a
hosted media URL which is used directly as the ``media_uri`` (persistence to GCS
is a service concern in v3).

The real ``fal_client`` call is isolated in :meth:`FalProvider._call`. Latency
is measured in ``generate`` and reported in SECONDS.
"""
from __future__ import annotations

import os
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


def _extract_video_url(result: dict[str, Any]) -> str | None:
    video = result.get("video")
    if isinstance(video, dict) and video.get("url"):
        return video["url"]
    if result.get("video_url"):
        return result["video_url"]
    return result.get("url")


@register_cls("fal")
class FalProvider:
    provider_id: str = "fal"

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
                                    error=out.get("error") or "no video returned",
                                    latency_s=latency, raw=out.get("raw", {}))
        return GenerationResult(status=ExecStatus.SUCCESS, media_uri=media, latency_s=latency,
                                model_id=spec.model_id, duration=out.get("duration"),
                                raw=out.get("raw", {}))

    def _build_arguments(self, case: Case, spec: ModelSpec, p: dict[str, Any]) -> dict[str, Any]:
        """Shape the FAL request payload (mirrors v2 model-family branching)."""
        model_id = spec.model_id
        mode = (spec.type or case.mode or "t2v").lower()
        ratio = str(p.get("aspect_ratio") or "16:9")
        args: dict[str, Any] = {"prompt": case.prompt, "resolution": "720p"}

        is_kling_new = "kling-video/v3" in model_id or "kling-video/o3" in model_id
        is_kling_v3 = "kling-video/v3" in model_id
        is_grok = "grok-imagine" in model_id
        is_seedance2_r2v = model_id == "bytedance/seedance-2.0/reference-to-video"

        if "kling" in model_id:
            if is_kling_new:
                args["aspect_ratio"] = ratio
                args["generate_audio"] = True
            else:
                args["ratio"] = ratio
            args["duration"] = 10
        elif is_grok:
            args["aspect_ratio"] = ratio
            args["duration"] = 10
        elif "seedance-2.0" in model_id:
            args["aspect_ratio"] = ratio
            args["duration"] = "10"
            args["generate_audio"] = True
        else:
            args["aspect_ratio"] = ratio
            args["duration"] = 10

        assets = list(case.input_assets or [])
        if mode == "i2v" and assets:
            if is_kling_v3:
                args["start_image_url"] = assets[0]
            else:
                args["image_url"] = assets[0]
        if mode == "r2v" and assets:
            if is_kling_new:
                args["elements"] = [{"reference_image_urls": [u]} for u in assets]
            elif is_seedance2_r2v:
                args["image_urls"] = assets[:9]
            elif "seedance" in model_id:
                args["reference_images"] = [{"image_url": u} for u in assets]
            else:
                args["reference_images"] = assets
        return args

    async def _call(self, case: Case, spec: ModelSpec, p: dict[str, Any]) -> dict[str, Any]:
        import fal_client

        settings = get_settings()
        if settings.fal_key:
            os.environ.setdefault("FAL_KEY", settings.fal_key)
        args = self._build_arguments(case, spec, p)
        result = await fal_client.subscribe_async(spec.model_id, arguments=args)
        url = _extract_video_url(result if isinstance(result, dict) else {})
        return {"media_uri": url, "raw": {"original_url": url}}
