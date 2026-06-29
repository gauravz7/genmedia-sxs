"""Gemini 3.1 Flash TTS provider.

Synthesizes speech with `gemini-3.1-flash-tts-preview` via the genai
`models.generate_content` API with `response_modalities=["AUDIO"]` (Vertex /
service-account ADC).

NOTE (verified against google-genai 1.75.0, 2026-06-27): the TTS preview model
is NOT served by the experimental `client.interactions.create(...)` endpoint on
this project — that call returns HTTP 400 "Unsupported model interaction". The
working path is `client.models.generate_content` with a `speech_config`
(single- or multi-speaker), which returns 24kHz mono 16-bit PCM in
`resp.candidates[0].content.parts[0].inline_data.data`. We therefore use that
path here.

Supports:

  * single-speaker (one of the 30 prebuilt voices)
  * multi-speaker (<=2 speakers, names must match the transcript)
  * director-style natural-language style prompt prepended to the transcript
  * inline audio tags ([whispers], [shouting], [laughs], ...)

The raw audio payload is 24kHz mono 16-bit PCM (base64). We wrap it into a WAV
container with the stdlib `wave` module and upload to GCS under `audio/`.

The model is documented to occasionally 500 or to emit text tokens instead of
audio (and to mis-read the director's notes aloud / false-reject as
PROHIBITED_CONTENT). To harden against this we:
  * add an explicit synthesis preamble that labels where the transcript begins,
  * retry up to MAX_ATTEMPTS times with backoff,
  * treat "no audio payload" as a retryable failure.

No module-level network calls: the client is built lazily inside the function.
"""

import asyncio
import base64
import io
import os
import time
import wave
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from google import genai
from google.genai import types

from util.gcs_utils import upload_from_bytes

load_dotenv()

PROJECT_ID = os.getenv("GCP_PROJECT_ID", "vital-octagon-19612")
TTS_LOCATION = os.getenv("TTS_LOCATION", "global")
GEMINI_TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-3.1-flash-tts-preview")
MODEL_LABEL = "Gemini 3.1 Flash TTS"

MAX_ATTEMPTS = 3

# The 30 prebuilt voices (for validation / UI). First is the default.
PREBUILT_VOICES = [
    "Kore", "Puck", "Zephyr", "Charon", "Fenrir", "Leda", "Orus", "Aoede",
    "Callirrhoe", "Autonoe", "Enceladus", "Iapetus", "Umbriel", "Algieba",
    "Despina", "Erinome", "Algenib", "Rasalgethi", "Laomedeia", "Achernar",
    "Alnilam", "Schedar", "Gacrux", "Pulcherrima", "Achird", "Zubenelgenubi",
    "Vindemiatrix", "Sadachbia", "Sadaltager", "Sulafat",
]
DEFAULT_VOICE = "Kore"

# Audio sample params for the WAV wrapper (per the model's documented output).
SAMPLE_RATE_HZ = 24000
SAMPLE_WIDTH_BYTES = 2  # 16-bit
CHANNELS = 1


def _standard_result(model: str, **kwargs) -> dict:
    base = {"model": model}
    base.update(kwargs)
    return base


def _pcm_to_wav(pcm: bytes) -> bytes:
    """Wrap raw 24kHz/mono/16-bit PCM into a WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH_BYTES)
        wf.setframerate(SAMPLE_RATE_HZ)
        wf.writeframes(pcm)
    return buf.getvalue()


def _build_speech_config(voice: str, speakers: Optional[List[dict]]):
    """Build a typed `types.SpeechConfig` — single- or multi-speaker.

    Single: one prebuilt voice.
    Multi : up to 2 speakers; each speaker name must appear in the transcript.
    """
    if speakers:
        cfgs = []
        for s in speakers[:2]:  # model caps at 2 speakers
            name = s.get("speaker") or s.get("name")
            v = s.get("voice") or DEFAULT_VOICE
            if name:
                cfgs.append(
                    types.SpeakerVoiceConfig(
                        speaker=name,
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=v)
                        ),
                    )
                )
        if cfgs:
            return types.SpeechConfig(
                multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
                    speaker_voice_configs=cfgs
                )
            )
    return types.SpeechConfig(
        voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                voice_name=voice or DEFAULT_VOICE
            )
        )
    )


def _build_prompt(
    text: str,
    style_prompt: Optional[str],
    language: Optional[str],
    speakers: Optional[List[dict]],
) -> str:
    """Compose the director's-notes + transcript prompt.

    A clear synthesis preamble keeps the model from reading the directions
    aloud. IMPORTANT: the TTS preview model rejects (400 INVALID_ARGUMENT) any
    single-quoted token that contains a colon (e.g. 'TRANSCRIPT:'), so the
    preamble below deliberately avoids quoted-colon delimiters and keeps the
    section headers plain.
    """
    lines: List[str] = []
    lines.append(
        "Read the transcript below aloud as natural, expressive spoken audio. "
        "Use any style notes only to guide your delivery; do not speak the "
        "style notes, section headers, speaker labels, or bracketed performance "
        "cues (such as [whispers] or [excited]) out loud."
    )
    if style_prompt:
        lines.append("")
        lines.append(f"Style: {style_prompt.strip()}")
    if language:
        lines.append(f"Language: {language}")
    if speakers:
        names = ", ".join(
            s.get("speaker") or s.get("name") or "" for s in speakers[:2]
        )
        lines.append(
            f"This is a multi-speaker dialogue between {names}. Each line is "
            "prefixed with the speaker name."
        )
    lines.append("")
    lines.append("Transcript:")
    lines.append(text or "")
    return "\n".join(lines)


def _extract_audio_pcm(resp) -> Optional[bytes]:
    """Pull raw PCM out of a generate_content response.

    Primary path (google-genai 1.75.0):
        resp.candidates[0].content.parts[*].inline_data.data  (bytes, already
        decoded by the SDK; base64-decode only if it arrives as a str).
    Tolerant of shape — scans all candidates/parts for the first audio blob.
    """
    candidates = getattr(resp, "candidates", None) or []
    for cand in candidates:
        content = getattr(cand, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
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


def _synthesize_once(prompt_text: str, speech_config) -> bytes:
    """One blocking synthesis attempt. Raises on no-audio / API error."""
    client = genai.Client(
        vertexai=True,
        project=PROJECT_ID,
        location=TTS_LOCATION,
        http_options=types.HttpOptions(timeout=300000),  # ms (=5 min)
    )
    config = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=speech_config,
    )
    resp = client.models.generate_content(
        model=GEMINI_TTS_MODEL,
        contents=prompt_text,
        config=config,
    )
    pcm = _extract_audio_pcm(resp)
    if not pcm:
        raise RuntimeError(
            "Gemini TTS returned no audio payload (likely text tokens instead "
            "of audio — retryable)"
        )
    return pcm


async def generate_gemini_tts(
    text: str,
    voice: str = DEFAULT_VOICE,
    style_prompt: Optional[str] = None,
    speakers: Optional[List[dict]] = None,
    language: Optional[str] = None,
    case_id: str = "case",
) -> dict:
    """Generate speech on Gemini 3.1 Flash TTS. Returns the standard result dict.

    Shape: {model, url, gcs_url, latency_ms, status, error}
    """
    start = time.time()
    prompt_text = _build_prompt(text, style_prompt, language, speakers)
    speech_config = _build_speech_config(voice, speakers)

    last_err: Optional[str] = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            pcm = await asyncio.to_thread(_synthesize_once, prompt_text, speech_config)
            wav_bytes = _pcm_to_wav(pcm)
            safe_id = "".join(c if c.isalnum() else "-" for c in str(case_id)).strip("-").lower() or "case"
            filename = f"audio/tts_gemini_{safe_id}_{int(time.time()*1000)}.wav"
            gcs_url = upload_from_bytes(wav_bytes, filename, content_type="audio/wav")
            return _standard_result(
                MODEL_LABEL,
                status="success",
                url=gcs_url,
                gcs_url=gcs_url,
                latency_ms=round((time.time() - start) * 1000),
                voice=voice,
                error=None,
                result={"url": gcs_url},
            )
        except Exception as e:
            last_err = str(e)
            # Short backoff before retrying (model 500s / transient classifier).
            if attempt < MAX_ATTEMPTS:
                await asyncio.sleep(1.5 * attempt)

    return _standard_result(
        MODEL_LABEL,
        status="error",
        error=f"Failed after {MAX_ATTEMPTS} attempts: {last_err}",
        latency_ms=round((time.time() - start) * 1000),
        url=None,
        gcs_url=None,
    )
