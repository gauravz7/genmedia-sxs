"""ElevenLabs TTS provider (ports v2 ``elevenlabs_provider.py``).

Synthesizes speech via the ElevenLabs REST API (Eleven v3 with a v2 fallback),
uploads the mp3 to GCS, and returns the ``gs://`` URI as ``media_uri``. Provider
id ``elevenlabs``.

The real HTTP synthesis + upload live in :meth:`ElevenLabsProvider._call`.
Latency is measured in ``generate`` and reported in SECONDS.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from app.config import get_settings
from app.domain.models import Case, ExecStatus, GenerationResult, ModelSpec
from app.providers.base import register_cls

VOICE_MAP = {
    "George": "JBFqnCBsd6RMkjVDRZzb", "Sarah": "EXAVITQu4vr4xnSDxMaL",
    "Laura": "FGY2WhTYpPnrIDTdsKH5", "Charlie": "IKne3meq5aSn9XLyUdCD",
    "Rachel": "21m00Tcm4TlvDq8ikWAM",
}
DEFAULT_VOICE_NAME = "George"
DEFAULT_VOICE_ID = VOICE_MAP[DEFAULT_VOICE_NAME]
_OUTPUT_FMT = "mp3_44100_128"
TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech"


def _effective_params(case: Case, override: dict[str, Any] | None) -> dict[str, Any]:
    p = dict(case.params or {})
    if override:
        p.update(override)
    return p


def _resolve_voice(voice: Any) -> str:
    v = str(voice or "").strip()
    if v and len(v) >= 20 and " " not in v:
        return v
    if v in VOICE_MAP:
        return VOICE_MAP[v]
    return DEFAULT_VOICE_ID


@register_cls("elevenlabs")
class ElevenLabsProvider:
    provider_id: str = "elevenlabs"

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
                                    error=out.get("error") or "ElevenLabs returned no audio",
                                    latency_s=latency, raw=out.get("raw", {}))
        return GenerationResult(status=ExecStatus.SUCCESS, media_uri=media, latency_s=latency,
                                model_id=spec.model_id, raw=out.get("raw", {}))

    async def _call(self, case: Case, spec: ModelSpec, p: dict[str, Any]) -> dict[str, Any]:
        import requests

        from app.infra.gcs import GcsClient

        settings = get_settings()
        if not settings.elevenlabs_api_key:
            raise RuntimeError("ELEVENLABS_API_KEY not set")
        model = spec.model_id or settings.elevenlabs_model
        voice_id = _resolve_voice(p.get("voice"))
        text = case.prompt or ""

        def _run() -> bytes:
            resp = requests.post(
                f"{TTS_URL}/{voice_id}?output_format={_OUTPUT_FMT}",
                headers={"xi-api-key": settings.elevenlabs_api_key,
                         "Content-Type": "application/json", "Accept": "audio/mpeg"},
                json={"text": text, "model_id": model,
                      "voice_settings": {"stability": 0.5, "use_speaker_boost": True}},
                timeout=180)
            if resp.status_code != 200:
                raise RuntimeError(f"ElevenLabs HTTP {resp.status_code}: {resp.text[:300]}")
            if not resp.content:
                raise RuntimeError("ElevenLabs returned empty audio")
            return resp.content

        mp3 = await asyncio.to_thread(_run)
        gcs = GcsClient(settings.gcs_bucket_name)
        uri = gcs.upload_bytes(mp3, f"audio/tts_elevenlabs_{int(time.time() * 1000)}.mp3",
                               content_type="audio/mpeg")
        return {"media_uri": uri, "raw": {"voice_id": voice_id, "model_used": model}}
