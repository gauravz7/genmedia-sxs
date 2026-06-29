"""ElevenLabs TTS provider (REST via `requests`).

Synthesizes speech with ElevenLabs `eleven_multilingual_v2` and uploads the
returned mp3 to GCS under `audio/`. Mirrors the standard provider result shape
used by the Gemini TTS provider so the pipeline can treat both identically.

Controls are mapped from our generic case schema:
  * voice (a name, e.g. "Rachel")        -> ElevenLabs voice_id (VOICE_MAP)
  * style_prompt / emotion               -> voice_settings (stability/style)
  * Gemini-only inline [audio tags]       -> stripped from the text
  * pacing                                -> handled inline in the text

The ElevenLabs API key is read from env (ELEVENLABS_API_KEY), loaded via
python-dotenv like the other providers. No module-level network calls.
"""

import asyncio
import os
import re
import time
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

from util.gcs_utils import upload_from_bytes

load_dotenv()

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2")
MODEL_LABEL = "ElevenLabs (multilingual v2)"
API_BASE = "https://api.elevenlabs.io/v1/text-to-speech"

# Name -> ElevenLabs prebuilt voice_id. These are the well-known default
# ElevenLabs voices. "Rachel" is the default. Unknown names fall back to the
# default voice_id.
VOICE_MAP: Dict[str, str] = {
    "Rachel": "21m00Tcm4TlvDq8ikWAM",
    "Domi": "AZnzlk1XvdvUeBnXmlld",
    "Bella": "EXAVITQu4vr4xnSDxMaL",
    "Antoni": "ErXwobaYiN019PkySvjV",
    "Elli": "MF3mGyEYCl7XYWbV9V6O",
    "Josh": "TxGEqnHWrfWFTfGW9XjX",
    "Arnold": "VR6AewLTigWG4xSOukaG",
    "Adam": "pNInz6obpgDQGcFmaJgB",
    "Sam": "yoZ06aMxZJJ28mfd3POQ",
}
DEFAULT_VOICE_NAME = "Rachel"
DEFAULT_VOICE_ID = VOICE_MAP[DEFAULT_VOICE_NAME]

# Gemini-only inline audio tags to strip from ElevenLabs text (it does not
# understand them). A couple map to nearest-equivalent voice_settings nudges.
_TAG_RE = re.compile(r"\[[^\]]+\]")
_EXPRESSIVE_TAGS = {
    "excited", "shouting", "laughs", "laughing", "angry", "crying",
    "whispers", "whispering", "sarcastic", "sighs",
}


def _standard_result(model: str, **kwargs) -> dict:
    base = {"model": model}
    base.update(kwargs)
    return base


def _resolve_voice_id(voice: Optional[str]) -> str:
    """Resolve a voice name (or raw id) to an ElevenLabs voice_id."""
    if not voice:
        return DEFAULT_VOICE_ID
    # If it already looks like a 20-char ElevenLabs id, pass through.
    if len(voice) >= 20 and " " not in voice:
        return voice
    return VOICE_MAP.get(voice, DEFAULT_VOICE_ID)


def _clean_text(text: str, speakers: Optional[List[dict]]) -> tuple:
    """Strip Gemini inline tags; detect expressiveness; flatten speaker labels.

    Returns (cleaned_text, had_expressive_tag).
    """
    raw = text or ""
    tags = [t.strip("[]").lower() for t in _TAG_RE.findall(raw)]
    had_expressive = any(t in _EXPRESSIVE_TAGS for t in tags)
    cleaned = _TAG_RE.sub("", raw)
    # For multi-speaker scripts, keep the "Name: line" form — it reads fine as
    # prose for a single-voice ElevenLabs render; just collapse extra whitespace.
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, had_expressive


def _voice_settings(style_prompt: Optional[str], had_expressive: bool) -> dict:
    """Map style/emotion hints to ElevenLabs voice_settings.

    Defaults follow the documented sensible baseline; expressive cues lower
    stability and raise style for more dynamic delivery.
    """
    stability = 0.5
    similarity = 0.75
    style = 0.0
    blob = (style_prompt or "").lower()
    if had_expressive or any(
        w in blob for w in ("expressive", "dramatic", "excited", "energetic", "emotional")
    ):
        stability = 0.3
        style = 0.5
    if any(w in blob for w in ("calm", "neutral", "monotone", "documentary")):
        stability = 0.7
        style = 0.0
    return {
        "stability": stability,
        "similarity_boost": similarity,
        "style": style,
        "use_speaker_boost": True,
    }


def _synthesize_once(voice_id: str, text: str, settings: dict) -> bytes:
    """One blocking ElevenLabs synthesis call. Raises on error/empty."""
    if not ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY not set in environment")
    resp = requests.post(
        f"{API_BASE}/{voice_id}",
        headers={
            "xi-api-key": ELEVENLABS_API_KEY,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        json={
            "text": text,
            "model_id": ELEVENLABS_MODEL,
            "voice_settings": settings,
        },
        timeout=180,
    )
    if resp.status_code != 200:
        # Surface the API's verbatim error body for debugging.
        raise RuntimeError(
            f"ElevenLabs HTTP {resp.status_code}: {resp.text[:500]}"
        )
    if not resp.content:
        raise RuntimeError("ElevenLabs returned empty audio")
    return resp.content


async def generate_elevenlabs_tts(
    text: str,
    voice: str = DEFAULT_VOICE_NAME,
    style_prompt: Optional[str] = None,
    speakers: Optional[List[dict]] = None,
    language: Optional[str] = None,
    case_id: str = "case",
) -> dict:
    """Generate speech on ElevenLabs. Returns the standard result dict.

    Shape: {model, url, gcs_url, latency_ms, status, error}
    """
    start = time.time()
    voice_id = _resolve_voice_id(voice)
    cleaned, had_expressive = _clean_text(text, speakers)
    settings = _voice_settings(style_prompt, had_expressive)

    try:
        mp3 = await asyncio.to_thread(_synthesize_once, voice_id, cleaned, settings)
        safe_id = "".join(c if c.isalnum() else "-" for c in str(case_id)).strip("-").lower() or "case"
        filename = f"audio/tts_elevenlabs_{safe_id}_{int(time.time()*1000)}.mp3"
        gcs_url = upload_from_bytes(mp3, filename, content_type="audio/mpeg")
        return _standard_result(
            MODEL_LABEL,
            status="success",
            url=gcs_url,
            gcs_url=gcs_url,
            latency_ms=round((time.time() - start) * 1000),
            voice=voice,
            voice_id=voice_id,
            error=None,
            result={"url": gcs_url},
        )
    except Exception as e:
        return _standard_result(
            MODEL_LABEL,
            status="error",
            error=str(e),
            latency_ms=round((time.time() - start) * 1000),
            url=None,
            gcs_url=None,
        )
