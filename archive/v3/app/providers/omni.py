"""Omni provider — Gemini Omni Flash video via the Interactions API (EAP).

Ports v2 ``omni_provider.py``. Aspect ratio / duration are conveyed in the
prompt per EAP guidance; the model returns video bytes which are uploaded to GCS
and the resulting ``gs://`` URI becomes the ``media_uri``.

The real Interactions call + GCS upload live in :meth:`OmniProvider._call`.
Latency is measured in ``generate`` and reported in SECONDS.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from app.config import get_settings
from app.domain.models import Case, ExecStatus, GenerationResult, ModelSpec
from app.providers.base import register_cls

OMNI_ALLOWED_PROJECTS = {"vital-octagon-19612", "cloud-llm-preview1"}


def _effective_params(case: Case, override: dict[str, Any] | None) -> dict[str, Any]:
    p = dict(case.params or {})
    if override:
        p.update(override)
    return p


def _g(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _extract_video_bytes(interaction: Any) -> bytes | None:
    import base64
    for step in (_g(interaction, "steps") or []):
        if _g(step, "type") not in (None, "model_output"):
            continue
        for part in (_g(step, "content") or []):
            data = _g(part, "data")
            if not data:
                continue
            mime = _g(part, "mime_type") or ""
            if "video" in mime or _g(part, "type") == "video":
                try:
                    return base64.b64decode(data)
                except Exception:
                    continue
    return None


@register_cls("omni")
class OmniProvider:
    provider_id: str = "omni"

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
                                    error=out.get("error") or "no video returned by Omni",
                                    latency_s=latency, raw=out.get("raw", {}))
        return GenerationResult(status=ExecStatus.SUCCESS, media_uri=media, latency_s=latency,
                                model_id=spec.model_id, raw=out.get("raw", {}))

    async def _call(self, case: Case, spec: ModelSpec, p: dict[str, Any]) -> dict[str, Any]:
        from google import genai
        from google.genai import types

        from app.infra.gcs import GcsClient

        settings = get_settings()
        project = settings.omni_project or settings.gcp_project_id
        if project not in OMNI_ALLOWED_PROJECTS:
            return {"error": f"Project '{project}' not in Omni EAP allowlist "
                             f"{sorted(OMNI_ALLOWED_PROJECTS)}", "raw": {}}

        mode = (spec.type or case.mode or "t2v").lower()
        ratio = str(p.get("aspect_ratio") or "16:9")
        prompt = case.prompt
        hints = []
        if ratio and ratio not in prompt:
            hints.append(f"{ratio} aspect ratio")
        if not any(s in prompt.lower() for s in ("second video", "seconds.")):
            hints.append("8 second video")
        if hints:
            prompt = f"{prompt}. {'. '.join(hints)}."

        def _run() -> bytes | None:
            client = genai.Client(
                vertexai=True, project=project, location=settings.omni_location,
                http_options=types.HttpOptions(
                    timeout=600000,
                    headers={"Api-Revision": settings.omni_api_revision}
                    if settings.omni_api_revision else None))
            if mode == "t2v":
                payload: Any = prompt
            else:
                parts: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
                # (Image parts would be inlined here in prod; omitted for brevity.)
                payload = parts
            interaction = client.interactions.create(model=spec.model_id, input=payload)
            return _extract_video_bytes(interaction)

        video_bytes = await asyncio.to_thread(_run)
        if not video_bytes:
            return {"error": "No video returned by Omni", "raw": {}}
        gcs = GcsClient(settings.gcs_bucket_name)
        uri = gcs.upload_bytes(video_bytes, f"omni_{int(time.time() * 1000)}.mp4",
                               content_type="video/mp4")
        return {"media_uri": uri, "raw": {"project": project, "mode": mode}}
