"""ElevenLabs TTS provider (REST via `requests`).

Primary model is **Eleven v3** (`eleven_v3`) — expressive, supports inline audio
tags ([excited], [whispers], …) and 70+ languages. Multi-speaker cases use the
**Text to Dialogue API** (`/v1/text-to-dialogue`, v3-only). If a v3 call fails
(e.g. the key isn't enabled for v3), we automatically fall back to
`eleven_multilingual_v2` so generation never hard-breaks.

Per-language native voices: when `ELEVENLABS_USE_NATIVE=1` and the case language
maps to a known native voice (LANG_VOICE), that voice is used; otherwise a
default account voice is used (multilingual models speak any language with any
voice). Native library voices must first be added to the account — see
`setup_elevenlabs_voices.py`.

Docs:
  - v3 model / tags:  https://elevenlabs.io/docs/overview/models
  - Text to Dialogue: https://elevenlabs.io/docs/api-reference/text-to-dialogue/convert
  - v3 prompting:     https://elevenlabs.io/docs/overview/capabilities/text-to-speech/best-practices

ELEVENLABS_API_KEY is read from env (loaded via python-dotenv). No module-level
network calls.
"""

import asyncio
import os
import re
import time
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

from util.gcs_utils import upload_from_bytes
from util.ratelimit import retry as _retry, gate

load_dotenv()

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
PRIMARY_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_v3")
FALLBACK_MODEL = os.getenv("ELEVENLABS_FALLBACK_MODEL", "eleven_multilingual_v2")
USE_NATIVE = os.getenv("ELEVENLABS_USE_NATIVE", "1") not in ("0", "false", "False", "")
MODEL_LABEL = "ElevenLabs (v3)"

TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech"
DIALOGUE_URL = "https://api.elevenlabs.io/v1/text-to-dialogue"
_OUTPUT_FMT = "mp3_44100_128"

# --- Account voices (verified present on the workspace) ---------------------
VOICE_MAP: Dict[str, str] = {
    "George": "JBFqnCBsd6RMkjVDRZzb",   # warm storyteller (default)
    "Sarah": "EXAVITQu4vr4xnSDxMaL",
    "Laura": "FGY2WhTYpPnrIDTdsKH5",
    "Charlie": "IKne3meq5aSn9XLyUdCD",
    "Roger": "CwhRBWXzGAHq8TQ4Fs17",
    "Callum": "N2lVS1w4EtoT3dr4eOWO",
    "River": "SAz9YHcvj6GT2YYXdXww",
    "Liam": "TX3LPaxmHKxFdv7VOQHJ",
    "Alice": "Xb7hH8MSUJpSbSDYk0k2",
    "Matilda": "XrExE9yKIg1WjnnlVkGX",
    "Will": "bIHbv24MWmeRgasZH58o",
    "Harry": "SOYHLrjzK2X1ezoPC6cr",
    "Rachel": "21m00Tcm4TlvDq8ikWAM",
}
DEFAULT_VOICE_NAME = "George"
DEFAULT_VOICE_ID = VOICE_MAP[DEFAULT_VOICE_NAME]
# Round-robin voices for multi-speaker dialogue turns.
DIALOGUE_VOICES = [VOICE_MAP["George"], VOICE_MAP["Sarah"], VOICE_MAP["Charlie"], VOICE_MAP["Laura"]]

# --- Popular native voices per language (ElevenLabs voice library) ----------
# NOTE: library voices must be ADDED to the account before use (run
# setup_elevenlabs_voices.py). Override this map with the confirmed account
# voice_ids that script prints. Base language code (before any '-') is matched.
LANG_VOICE: Dict[str, str] = {
    "hi": "dSEhEXLzhnZEytnJ2rRy",   # Hindi  — Anika
    "ta": "",                        # Tamil  — set via setup script
    "te": "",                        # Telugu — set via setup script
    "ja": "6l0ObIy4mHn0XfeKlCgW",   # Japanese — Maya
    "ko": "i4rvH83fgM9aBqIBZ5zH",   # Korean — Jihu
    "zh": "hFamrilbAE6WDMtWgKvu",   # Chinese (Mandarin) — Pangge
    "es": "9gm2jXcKEKzgaypKoOlk",   # Spanish — Alejandro
    "fr": "BilXxxvRLrA8YTteM2sl",   # French — Oris
    "de": "JvlnClXqQd2HerGRtXEe",   # German — Benedict
    "ar": "aMmeBf0lzDYlouyfqNjh",   # Arabic — Maryam
    "pt": "9K5K6kEHsM7u8gMJHU9C",   # Portuguese — Monica
}

_TAG_RE = re.compile(r"\[[^\]]+\]")


def _standard_result(model: str, **kwargs) -> dict:
    base = {"model": model}
    base.update(kwargs)
    return base


def _resolve_voice(voice: Optional[str], language: Optional[str]) -> str:
    """Explicit voice wins; else a native voice for the language (if enabled and
    known); else the default account voice."""
    if voice:
        if len(voice) >= 20 and " " not in voice:
            return voice  # already a voice_id
        if voice in VOICE_MAP:
            return VOICE_MAP[voice]
    if USE_NATIVE and language:
        base = str(language).strip().lower().split("-")[0]
        vid = LANG_VOICE.get(base)
        if vid:
            return vid
    return DEFAULT_VOICE_ID


def _strip_tags(text: str) -> str:
    return re.sub(r"[ \t]+", " ", _TAG_RE.sub("", text or "")).strip()


def _voice_settings(model: str, style_prompt: Optional[str]) -> dict:
    """Model-aware settings. Eleven v3 only accepts stability in {0.0, 0.5, 1.0}
    (Creative / Natural / Robust); v2 accepts continuous values + style."""
    blob = (style_prompt or "").lower()
    expressive = any(w in blob for w in ("expressive", "dramatic", "excited", "energetic", "emotional", "lively"))
    calm = any(w in blob for w in ("calm", "neutral", "monotone", "documentary", "serious"))
    if str(model).startswith("eleven_v3"):
        stability = 0.0 if expressive else (1.0 if calm else 0.5)
        return {"stability": stability}
    stability = 0.3 if expressive else (0.7 if calm else 0.5)
    return {
        "stability": stability,
        "similarity_boost": 0.75,
        "style": 0.5 if expressive else 0.0,
        "use_speaker_boost": True,
    }


def _headers() -> dict:
    if not ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY not set in environment")
    return {"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json", "Accept": "audio/mpeg"}


def _parse_turns(text: str, speakers: Optional[List[dict]]) -> List[dict]:
    """Parse a multi-speaker script ("Name: line") into ElevenLabs dialogue
    inputs [{text, voice_id}], assigning each distinct speaker an account voice
    by order. Audio tags are kept (v3 understands them)."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    turns: List[dict] = []
    order: Dict[str, str] = {}
    for ln in lines:
        m = re.match(r"^\s*([A-Za-z0-9 _'-]{1,30}?)\s*:\s*(.+)$", ln)
        if not m:
            # continuation of previous turn
            if turns:
                turns[-1]["text"] += " " + ln
            continue
        name, utt = m.group(1).strip(), m.group(2).strip()
        if name not in order:
            order[name] = DIALOGUE_VOICES[len(order) % len(DIALOGUE_VOICES)]
        turns.append({"text": utt, "voice_id": order[name]})
    return turns


def _post_tts(voice_id: str, text: str, model: str, style_prompt: Optional[str]) -> bytes:
    resp = requests.post(
        f"{TTS_URL}/{voice_id}?output_format={_OUTPUT_FMT}",
        headers=_headers(),
        json={"text": text, "model_id": model, "voice_settings": _voice_settings(model, style_prompt)},
        timeout=180,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"ElevenLabs TTS HTTP {resp.status_code}: {resp.text[:300]}")
    if not resp.content:
        raise RuntimeError("ElevenLabs returned empty audio")
    return resp.content


def _post_dialogue(inputs: List[dict], model: str, style_prompt: Optional[str]) -> bytes:
    resp = requests.post(
        f"{DIALOGUE_URL}?output_format={_OUTPUT_FMT}",
        headers=_headers(),
        json={"model_id": model, "inputs": inputs, "settings": _voice_settings(model, style_prompt)},
        timeout=240,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"ElevenLabs Dialogue HTTP {resp.status_code}: {resp.text[:300]}")
    if not resp.content:
        raise RuntimeError("ElevenLabs returned empty dialogue audio")
    return resp.content


def _synthesize(text: str, voice_id: str, speakers: Optional[List[dict]], style_prompt: Optional[str]) -> tuple:
    """Try v3 (with audio tags + dialogue for multi-speaker); on failure fall
    back to multilingual_v2 (tags stripped, single voice). Returns
    (audio_bytes, model_used)."""
    turns = _parse_turns(text, speakers) if speakers else []
    # Primary: Eleven v3 (retried on 429/5xx with backoff)
    try:
        if len(turns) >= 2 and PRIMARY_MODEL == "eleven_v3":
            return _retry(lambda: _post_dialogue(turns, PRIMARY_MODEL, style_prompt)), f"{PRIMARY_MODEL} (dialogue)"
        return _retry(lambda: _post_tts(voice_id, text, PRIMARY_MODEL, style_prompt)), PRIMARY_MODEL
    except Exception as primary_err:
        # Fallback: multilingual_v2 (no tags, single voice convert)
        try:
            return _retry(lambda: _post_tts(voice_id, _strip_tags(text), FALLBACK_MODEL, style_prompt)), FALLBACK_MODEL
        except Exception:
            raise primary_err


async def generate_elevenlabs_tts(
    text: str,
    voice: str = DEFAULT_VOICE_NAME,
    style_prompt: Optional[str] = None,
    speakers: Optional[List[dict]] = None,
    language: Optional[str] = None,
    case_id: str = "case",
) -> dict:
    """Generate speech on ElevenLabs (v3 → v2 fallback). Returns the standard
    result dict: {model, url, gcs_url, latency_ms, status, error, voice, voice_id}."""
    start = time.time()
    voice_id = _resolve_voice(voice, language)
    try:
        async with gate("elevenlabs"):  # cap concurrent ElevenLabs requests
            mp3, model_used = await asyncio.to_thread(_synthesize, text, voice_id, speakers, style_prompt)
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
            model_used=model_used,
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
