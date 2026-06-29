"""TTS AI judge — multimodal-audio pairwise evaluation.

`run_tts_evaluation(job_id)` loads a TTS job's two generated audio clips (the
blind A/B sides), sends both to a Gemini multimodal model as audio inputs, and
asks for per-side 1-5 scores on:

  * Naturalness
  * Style / prompt adherence
  * Expressiveness
  * Pacing
  * Pronunciation / clarity

plus an overall winner (A / B / tie). The verdict is mapped back to the engine
identity via the job's `side_map` and stored under the job's `ai_eval` field.

Robust to errors: any failure is recorded as `auto_eval_status = error` with the
message, and never raises out of the pipeline.

No module-level network calls — the genai client is built lazily.
"""

import json
import os
import time
from typing import Any, Dict, Optional

from google import genai
from google.genai import types

from util.gcs_utils import download_blob_to_bytes, normalize_gcs_url

TTS_COLLECTION = os.getenv("TTS_COLLECTION", "tts_jobs")
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "vital-octagon-19612")

EVAL_PROJECT = os.getenv("TTS_EVAL_PROJECT", os.getenv("EVAL_PROJECT", "cloud-llm-preview1"))
EVAL_LOCATION = os.getenv("EVAL_LOCATION", "global")
EVAL_MODEL = os.getenv("TTS_EVAL_MODEL", "gemini-2.5-flash")

METRICS = [
    "naturalness",
    "style_adherence",
    "expressiveness",
    "pacing",
    "pronunciation_clarity",
]

_eval_client = None


def _get_eval_client():
    global _eval_client
    if _eval_client is None:
        _eval_client = genai.Client(
            vertexai=True,
            project=EVAL_PROJECT,
            location=EVAL_LOCATION,
            http_options=types.HttpOptions(timeout=600000),
        )
    return _eval_client


def _get_firestore_client():
    from google.cloud import firestore
    return firestore.Client(project=GCP_PROJECT_ID)


def _audio_mime(url: str) -> str:
    ext = (url or "").split("?")[0].split(".")[-1].lower()
    if ext == "mp3":
        return "audio/mpeg"
    if ext == "wav":
        return "audio/wav"
    if ext == "ogg":
        return "audio/ogg"
    return "audio/wav"


def _result_url(res: dict) -> Optional[str]:
    if not isinstance(res, dict):
        return None
    return res.get("url") or res.get("gcs_url") or (res.get("result") or {}).get("url")


_SCORE_SCHEMA_HINT = (
    "Return ONLY JSON with this exact shape:\n"
    "{\n"
    '  "A": {"naturalness": 1-5, "style_adherence": 1-5, "expressiveness": 1-5, '
    '"pacing": 1-5, "pronunciation_clarity": 1-5, "comment": "string"},\n'
    '  "B": {"naturalness": 1-5, "style_adherence": 1-5, "expressiveness": 1-5, '
    '"pacing": 1-5, "pronunciation_clarity": 1-5, "comment": "string"},\n'
    '  "winner": "A" | "B" | "tie",\n'
    '  "justification": "string"\n'
    "}"
)


def _build_prompt(job: dict) -> str:
    text = job.get("text") or job.get("prompt") or ""
    style = job.get("style_prompt") or ""
    parts = [
        "You are an expert speech-quality judge for a blind side-by-side "
        "text-to-speech comparison. You will hear two audio clips: CLIP A then "
        "CLIP B. Both are renderings of the SAME script. Judge them blind — you "
        "do NOT know which TTS engine produced which clip.",
        "",
        "Score EACH clip 1-5 (5 = best) on:",
        "- naturalness: human-likeness, free of robotic/synthetic artifacts.",
        "- style_adherence: how well the delivery matches the requested style / "
        "director's notes and any emotion cues.",
        "- expressiveness: emotional range, intonation, dynamics.",
        "- pacing: rhythm, pauses, speed appropriateness.",
        "- pronunciation_clarity: correct, intelligible articulation.",
        "",
        f"SCRIPT (intended spoken text): {text!r}",
    ]
    if style:
        parts.append(f"REQUESTED STYLE / DIRECTOR'S NOTES: {style!r}")
    parts.append("")
    parts.append("Then pick the overall winner (A, B, or tie).")
    parts.append(_SCORE_SCHEMA_HINT)
    return "\n".join(parts)


def _to_int_1_5(v: Any) -> Optional[int]:
    try:
        n = int(round(float(v)))
        return max(1, min(5, n))
    except (TypeError, ValueError):
        return None


def _clean_side(raw: dict) -> dict:
    out = {}
    for m in METRICS:
        score = _to_int_1_5(raw.get(m))
        if score is not None:
            out[m] = score
    if raw.get("comment"):
        out["comment"] = str(raw["comment"])[:1000]
    scores = [out[m] for m in METRICS if m in out]
    if scores:
        out["overall_score"] = round(sum(scores) / len(scores), 2)
    return out


def run_tts_evaluation(job_id: str) -> None:
    """Run the multimodal-audio pairwise judge for one TTS job."""
    db = _get_firestore_client()
    doc_ref = db.collection(TTS_COLLECTION).document(job_id)
    snap = doc_ref.get()
    if not snap.exists:
        raise RuntimeError(f"TTS job {job_id} not found")
    job = snap.to_dict() or {}

    doc_ref.update({"auto_eval_status": "running"})

    results = job.get("results") or {}
    side_map = job.get("side_map") or {}
    a_url = _result_url(results.get("A"))
    b_url = _result_url(results.get("B"))

    # Need both sides to render a fair pairwise verdict.
    if not (a_url and b_url):
        doc_ref.update({
            "auto_eval_status": "error",
            "auto_eval_error": "One or both audio sides missing — cannot evaluate.",
        })
        return

    try:
        a_bytes = download_blob_to_bytes(normalize_gcs_url(a_url))
        b_bytes = download_blob_to_bytes(normalize_gcs_url(b_url))

        contents = [
            _build_prompt(job),
            "CLIP A:",
            types.Part.from_bytes(data=a_bytes, mime_type=_audio_mime(a_url)),
            "CLIP B:",
            types.Part.from_bytes(data=b_bytes, mime_type=_audio_mime(b_url)),
        ]
        config = types.GenerateContentConfig(
            temperature=0.2,
            response_mime_type="application/json",
        )

        client = _get_eval_client()
        delay = 6.0
        last_err = None
        parsed = None
        for attempt in range(4):
            try:
                resp = client.models.generate_content(
                    model=EVAL_MODEL, contents=contents, config=config
                )
                parsed = json.loads(resp.text)
                break
            except Exception as e:
                last_err = e
                if attempt < 3:
                    time.sleep(delay)
                    delay *= 2
        if parsed is None:
            raise RuntimeError(f"AI judge failed: {last_err}")

        side_a = _clean_side(parsed.get("A") or {})
        side_b = _clean_side(parsed.get("B") or {})
        winner_label = str(parsed.get("winner") or "").strip().upper()
        winner_engine = side_map.get(winner_label) if winner_label in ("A", "B") else None

        ai_eval = {
            "model": EVAL_MODEL,
            "evaluated_at": time.time(),
            "A": side_a,
            "B": side_b,
            "winner_side": winner_label if winner_label in ("A", "B", "TIE") else None,
            "winner_engine": winner_engine,
            "justification": str(parsed.get("justification") or "")[:2000],
            "side_map": side_map,
        }
        doc_ref.update({"ai_eval": ai_eval, "auto_eval_status": "done"})
    except Exception as e:
        doc_ref.update({"auto_eval_status": "error", "auto_eval_error": str(e)})
        raise
