"""Gemini TTS provider (ports v2 ``gemini_tts_provider.py``).

Synthesizes speech via ``client.models.generate_content`` with
``response_modalities=["AUDIO"]`` (returns 24kHz mono 16-bit PCM), wraps the PCM
in a WAV container, uploads to GCS, and returns the ``gs://`` URI. Provider id
``gemini_tts``.

The real synthesis + upload live in :meth:`GeminiTtsProvider._call`. Latency is
measured in ``generate`` and reported in SECONDS.
"""
from __future__ import annotations

import asyncio
import io
import time
import wave
from typing import Any

from app.config import get_settings
from app.domain.models import Case, ExecStatus, GenerationResult, ModelSpec
from app.providers.base import register_cls

DEFAULT_VOICE = "Kore"
SAMPLE_RATE_HZ = 24000
SAMPLE_WIDTH_BYTES = 2
CHANNELS = 1


def _effective_params(case: Case, override: dict[str, Any] | None) -> dict[str, Any]:
    p = dict(case.params or {})
    if override:
        p.update(override)
    return p


def _pcm_to_wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH_BYTES)
        wf.setframerate(SAMPLE_RATE_HZ)
        wf.writeframes(pcm)
    return buf.getvalue()


def _extract_audio_pcm(resp: Any) -> bytes | None:
    import base64
    for cand in (getattr(resp, "candidates", None) or []):
        content = getattr(cand, "content", None)
        for part in (getattr(content, "parts", None) or []):
            inline = getattr(part, "inline_data", None)
            data = getattr(inline, "data", None) if inline is not None else None
            if not data:
                continue
            mime = (getattr(inline, "mime_type", "") or "").lower()
            if "audio" in mime or "l16" in mime or "pcm" in mime:
                if isinstance(data, bytes):
                    return data
                try:
                    return base64.b64decode(data)
                except Exception:
                    continue
    return None


@register_cls("gemini_tts")
class GeminiTtsProvider:
    provider_id: str = "gemini_tts"

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
                                    error=out.get("error") or "Gemini TTS returned no audio",
                                    latency_s=latency, raw=out.get("raw", {}))
        return GenerationResult(status=ExecStatus.SUCCESS, media_uri=media, latency_s=latency,
                                model_id=spec.model_id, raw=out.get("raw", {}))

    async def _call(self, case: Case, spec: ModelSpec, p: dict[str, Any]) -> dict[str, Any]:
        from google import genai
        from google.genai import types

        from app.infra.gcs import GcsClient

        settings = get_settings()
        model = spec.model_id or settings.gemini_tts_model
        voice = str(p.get("voice") or DEFAULT_VOICE)
        text = case.prompt or ""

        def _run() -> bytes | None:
            client = genai.Client(vertexai=True, project=settings.gcp_project_id,
                                  location="global")
            speech_config = types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)))
            resp = client.models.generate_content(
                model=model, contents=text,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"], speech_config=speech_config))
            return _extract_audio_pcm(resp)

        pcm = await asyncio.to_thread(_run)
        if not pcm:
            return {"error": "Gemini TTS returned no audio payload", "raw": {}}
        wav = _pcm_to_wav(pcm)
        gcs = GcsClient(settings.gcs_bucket_name)
        uri = gcs.upload_bytes(wav, f"audio/tts_gemini_{int(time.time() * 1000)}.wav",
                               content_type="audio/wav")
        return {"media_uri": uri, "raw": {"voice": voice}}
