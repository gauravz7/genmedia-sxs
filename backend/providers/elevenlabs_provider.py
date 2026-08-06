"""ElevenLabs TTS provider — served through FAL.

ElevenLabs is not a Google model, so per the platform rule (Google → Vertex AI,
everything else → FAL) it is consumed via FAL rather than ElevenLabs' own REST
API. Two FAL endpoints back this module:

  - single speaker → ``fal-ai/elevenlabs/tts/eleven-v3``
  - multi speaker  → ``fal-ai/elevenlabs/text-to-dialogue/eleven-v3``

Both run **Eleven v3** — expressive, inline audio tags ([excited], [whispers], …)
and 70+ languages. There is no v2 fallback: FAL exposes each model as its own
slug, and 429/5xx are already retried with backoff by ``util.ratelimit.limited``.

Voices are passed by ElevenLabs voice_id (FAL also accepts a voice *name*).
Going through FAL removes the old "must be added to the workspace first"
constraint, so the per-language native voices in LANG_VOICE now apply whenever
``ELEVENLABS_USE_NATIVE`` is on and the case language maps to one.

Auth is FAL's (``FAL_KEY``); ``ELEVENLABS_API_KEY`` is no longer used.

Docs:
  - FAL Eleven v3:      https://fal.ai/models/fal-ai/elevenlabs/tts/eleven-v3
  - FAL Text-to-Dialogue: https://fal.ai/models/fal-ai/elevenlabs/text-to-dialogue/eleven-v3
  - v3 prompting:       https://elevenlabs.io/docs/overview/capabilities/text-to-speech/best-practices

No module-level network calls.
"""

import os
import re
import time
from typing import Any, Dict, List, Optional

import fal_client
from dotenv import load_dotenv

from util.gcs_utils import upload_from_url
from util.ratelimit import limited

load_dotenv()

USE_NATIVE = os.getenv("ELEVENLABS_USE_NATIVE", "1") not in ("0", "false", "False", "")
MODEL_LABEL = "ElevenLabs (v3)"

FAL_TTS_SLUG = os.getenv("ELEVENLABS_FAL_TTS_SLUG", "fal-ai/elevenlabs/tts/eleven-v3")
FAL_DIALOGUE_SLUG = os.getenv(
    "ELEVENLABS_FAL_DIALOGUE_SLUG", "fal-ai/elevenlabs/text-to-dialogue/eleven-v3"
)

# --- Curated voices ---------------------------------------------------------
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

# --- Native voices per language (ElevenLabs voice library) ------------------
# Base language code (before any '-') is matched.
LANG_VOICE: Dict[str, str] = {
    "hi": "dSEhEXLzhnZEytnJ2rRy",   # Hindi  — Anika
    "ta": "",                        # Tamil  — not yet chosen
    "te": "",                        # Telugu — not yet chosen
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
    """Explicit voice wins; else a native voice for the language (when enabled
    and known); else the default voice. Eleven v3 is multilingual, so the
    default voice still speaks the target language — just without a native
    accent — rather than the case erroring out."""
    if voice:
        if len(voice) >= 20 and " " not in voice:
            return voice           # already a voice_id
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


_EXPRESSIVE_WORDS = (
    "expressive", "dramatic", "excited", "energetic", "emotional", "lively",
    "upbeat", "cheerful", "enthusiastic", "playful", "animated", "angry",
    "shouting", "laughs", "whispers",
)
_MEDITATION_WORDS = ("meditation", "serene", "soothing", "guided relaxation")


def _stability(style_prompt: Optional[str], text: Optional[str] = None) -> float:
    """Eleven v3 accepts stability in {0.0, 0.5, 1.0} — Creative / Natural /
    Robust. Reserve the fully-flat Robust tier for true meditation; every other
    calm read caps at Natural, and expressive reads use Creative.

    The script's own inline audio tags count as intent: v3 only acts strongly on
    `[excited]` / `[whispers]` at the Creative tier, so a case tagged in the text
    but neutral in its style notes would otherwise be read flat. Only the tags
    are scanned, not the whole script — the word "angry" in a line of dialogue
    is content, not direction.
    """
    tags = " ".join(_TAG_RE.findall(text or "")).lower()
    blob = f"{(style_prompt or '').lower()} {tags}"
    if any(w in blob for w in _MEDITATION_WORDS):
        return 1.0
    return 0.0 if any(w in blob for w in _EXPRESSIVE_WORDS) else 0.5


def _parse_turns(text: str, speakers: Optional[List[dict]]) -> List[dict]:
    """Parse a multi-speaker script ("Name: line") into text-to-dialogue inputs
    [{text, voice}], assigning each distinct speaker a voice by order. Audio tags
    are kept (v3 understands them)."""
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
        turns.append({"text": utt, "voice": order[name]})
    return turns


def _extract_audio_url(result: Any) -> Optional[str]:
    """Pull the mp3 URL out of a FAL response ({"audio": {"url": ...}})."""
    if not isinstance(result, dict):
        return None
    audio = result.get("audio")
    if isinstance(audio, dict) and audio.get("url"):
        return audio["url"]
    if isinstance(audio, str) and audio:
        return audio
    if isinstance(result.get("audio_url"), str):
        return result["audio_url"]
    return result.get("url")


async def generate_elevenlabs_tts(
    text: str,
    voice: str = DEFAULT_VOICE_NAME,
    style_prompt: Optional[str] = None,
    speakers: Optional[List[dict]] = None,
    language: Optional[str] = None,
    case_id: str = "case",
) -> dict:
    """Generate speech on ElevenLabs v3 via FAL. Returns the standard result
    dict: {model, url, gcs_url, latency_ms, status, error, voice, voice_id}."""
    start = time.time()
    voice_id = _resolve_voice(voice, language)
    stability = _stability(style_prompt, text)

    # Multi-speaker scripts go to text-to-dialogue; a script that doesn't parse
    # into >= 2 turns falls through to the single-voice endpoint.
    turns = _parse_turns(text, speakers) if speakers else []
    if len(turns) >= 2:
        slug = FAL_DIALOGUE_SLUG
        arguments: Dict[str, Any] = {
            "inputs": turns,
            "stability": stability,
            "use_speaker_boost": True,
        }
        model_used = "eleven_v3 (dialogue)"
    else:
        slug = FAL_TTS_SLUG
        # Note: `language_code` is deliberately not sent — v3 auto-detects, and
        # the native-voice choice above already carries the language intent.
        arguments = {
            "text": text or "",
            "voice": voice_id,
            "stability": stability,
        }
        model_used = "eleven_v3"

    try:
        result = await limited("fal", lambda: fal_client.subscribe_async(slug, arguments=arguments))

        audio_url = _extract_audio_url(result)
        if not audio_url:
            raise RuntimeError(f"ElevenLabs via FAL returned no audio URL: {str(result)[:200]}")

        safe_id = "".join(c if c.isalnum() else "-" for c in str(case_id)).strip("-").lower() or "case"
        filename = f"audio/tts_elevenlabs_{safe_id}_{int(time.time()*1000)}.mp3"
        gcs_url = upload_from_url(audio_url, filename)

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
            result={"url": gcs_url, "original_url": audio_url},
        )
    except Exception as e:
        return _standard_result(
            MODEL_LABEL,
            status="error",
            error=str(e),
            latency_ms=round((time.time() - start) * 1000),
            voice=voice,
            voice_id=voice_id,
            model_used=model_used,
            url=None,
            gcs_url=None,
        )
