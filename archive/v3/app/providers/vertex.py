"""Vertex AI provider — Veo video generation (ports v2 ``vertex_provider.py``).

Handles t2v / i2v / r2v against Vertex Veo models. The Veo SDK writes the
result straight to GCS (``output_gcs_uri``) and returns a ``gs://`` URI, so no
extra upload step is needed here.

The real network/SDK work is isolated in :meth:`VertexProvider._call` so tests
can stub it. Latency is measured in ``generate`` and always reported in SECONDS
(fixing v2's seconds-vs-ms drift).
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from app.config import get_settings
from app.domain.models import Case, ExecStatus, GenerationResult, ModelSpec
from app.providers.base import register_cls


def _effective_params(case: Case, override: dict[str, Any] | None) -> dict[str, Any]:
    """Merge a case's params with a per-call override (override wins)."""
    p = dict(case.params or {})
    if override:
        p.update(override)
    return p


@register_cls("vertex")
class VertexProvider:
    provider_id: str = "vertex"

    async def generate(self, case: Case, spec: ModelSpec,
                       params: dict[str, Any] | None = None) -> GenerationResult:
        p = _effective_params(case, params)
        t0 = time.perf_counter()
        try:
            out = await self._call(case, spec, p)
        except Exception as exc:  # expected API error → normalized ERROR result
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
                                width=out.get("width"), height=out.get("height"),
                                fps=out.get("fps"), raw=out.get("raw", {}))

    async def _call(self, case: Case, spec: ModelSpec, p: dict[str, Any]) -> dict[str, Any]:
        """Real Veo SDK call (isolated for testability). Runs the blocking SDK in
        a thread and polls the long-running operation to completion."""
        from google import genai
        from google.genai import types

        settings = get_settings()
        mode = (spec.type or case.mode or "t2v").lower()
        ratio = str(p.get("aspect_ratio") or "16:9")
        duration = int(p.get("duration") or 8)
        resolution = str(p.get("resolution") or "720p")
        seed = int(p.get("seed") or 0) if str(p.get("seed") or "").isdigit() else 0

        bucket = settings.output_gcs_bucket or settings.gcs_bucket_name
        output_uri = f"gs://{bucket}/"

        def _run() -> dict[str, Any]:
            client = genai.Client(vertexai=True, project=settings.gcp_project_id,
                                  location="us-central1")
            source_kwargs: dict[str, Any] = {"prompt": case.prompt}
            if mode == "i2v" and case.input_assets:
                source_kwargs["image"] = types.Image(gcs_uri=case.input_assets[0],
                                                     mime_type="image/png")
            config_kwargs: dict[str, Any] = {
                "aspect_ratio": ratio,
                "number_of_videos": 1,
                "duration_seconds": duration,
                "person_generation": "allow_adult",
                "generate_audio": True,
                "resolution": resolution,
                "seed": seed,
                "output_gcs_uri": output_uri,
            }
            if mode == "r2v" and case.input_assets:
                refs = []
                for ref in case.input_assets:
                    ext = ref.split("?")[0].split(".")[-1].lower()
                    mime = "image/png" if ext == "png" else "image/jpeg"
                    refs.append(types.VideoGenerationReferenceImage(
                        image=types.Image(gcs_uri=ref, mime_type=mime),
                        reference_type="asset"))
                config_kwargs["reference_images"] = refs
            operation = client.models.generate_videos(
                model=spec.model_id,
                source=types.GenerateVideosSource(**source_kwargs),
                config=types.GenerateVideosConfig(**config_kwargs))
            while not operation.done:
                time.sleep(10)
                operation = client.operations.get(operation)
            response = operation.response
            if not response or not response.generated_videos:
                return {"error": "No videos generated", "raw": {}}
            video = response.generated_videos[0].video
            uri = getattr(video, "uri", None)
            return {"media_uri": uri, "duration": float(duration),
                    "raw": {"operation_id": operation.name, "mode": mode}}

        return await asyncio.to_thread(_run)
