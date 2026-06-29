"""Image AI judge — multimodal pairwise evaluation.

`run_image_evaluation(job_id)` loads an image job's two generated images (the
blind A/B sides), sends both to a Gemini multimodal model as image inputs, and
asks for per-side 1-5 scores on:

  * prompt_following   — how faithfully the image matches the prompt.
  * aesthetic          — overall aesthetic / composition quality.
  * detail             — sharpness, fine detail, resolution feel.
  * artifact_free      — absence of distortions / glitches / extra limbs etc.
  * edit_fidelity      — (I2I only) did it apply the requested edit while
                         preserving the rest of the original image?

plus an overall winner (A / B / tie) + justification. The verdict is mapped back
to the model identity via the job's `side_map` and stored under the job's
`ai_eval` field.

Robust to errors: any failure is recorded as `auto_eval_status = error` with the
message, and re-raised so the pipeline can mark it (the pipeline swallows it).

No module-level network calls — the genai client is built lazily.
"""

import json
import os
import time
from typing import Any, Dict, Optional

from google import genai
from google.genai import types

from util.gcs_utils import download_blob_to_bytes, normalize_gcs_url

IMAGE_COLLECTION = os.getenv("IMAGE_COLLECTION", "image_jobs")
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "vital-octagon-19612")

EVAL_PROJECT = os.getenv("IMAGE_EVAL_PROJECT", GCP_PROJECT_ID)
EVAL_LOCATION = os.getenv("EVAL_LOCATION", "global")
EVAL_MODEL = os.getenv("IMAGE_EVAL_MODEL", "gemini-2.5-flash")

# Base metrics scored on every job; edit_fidelity is added for I2I.
BASE_METRICS = ["prompt_following", "aesthetic", "detail", "artifact_free"]
EDIT_METRIC = "edit_fidelity"

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


def _image_mime(url: str) -> str:
    ext = (url or "").split("?")[0].split(".")[-1].lower()
    if ext in ("jpg", "jpeg"):
        return "image/jpeg"
    if ext == "webp":
        return "image/webp"
    if ext == "gif":
        return "image/gif"
    return "image/png"


def _result_url(res: dict) -> Optional[str]:
    if not isinstance(res, dict):
        return None
    return res.get("url") or res.get("gcs_url") or (res.get("result") or {}).get("url")


def _metrics_for(is_i2i: bool) -> list:
    return BASE_METRICS + ([EDIT_METRIC] if is_i2i else [])


def _schema_hint(is_i2i: bool) -> str:
    metrics = _metrics_for(is_i2i)
    side_fields = ", ".join(f'"{m}": 1-5' for m in metrics)
    return (
        "Return ONLY JSON with this exact shape:\n"
        "{\n"
        f'  "A": {{{side_fields}, "comment": "string"}},\n'
        f'  "B": {{{side_fields}, "comment": "string"}},\n'
        '  "winner": "A" | "B" | "tie",\n'
        '  "justification": "string"\n'
        "}"
    )


def _build_prompt(job: dict, is_i2i: bool) -> str:
    prompt = job.get("prompt") or ""
    parts = [
        "You are an expert image-quality judge for a blind side-by-side image "
        "comparison. You will see two images: IMAGE A then IMAGE B. Both were "
        "produced from the SAME prompt"
        + (" by editing the SAME input image." if is_i2i else ".")
        + " Judge them blind — you do NOT know which model produced which image.",
        "",
        "Score EACH image 1-5 (5 = best) on:",
        "- prompt_following: how faithfully the image satisfies the prompt.",
        "- aesthetic: overall aesthetic quality, composition, color, lighting.",
        "- detail: sharpness, fine detail, texture, resolution feel.",
        "- artifact_free: absence of distortions, glitches, malformed shapes, "
        "garbled text, extra/missing limbs.",
    ]
    if is_i2i:
        parts.append(
            "- edit_fidelity: did it apply the requested edit while preserving "
            "the rest of the original image (identity, layout, background)?"
        )
    parts.append("")
    parts.append(f"PROMPT (intended result): {prompt!r}")
    parts.append("")
    parts.append("Then pick the overall winner (A, B, or tie).")
    parts.append(_schema_hint(is_i2i))
    return "\n".join(parts)


def _to_int_1_5(v: Any) -> Optional[int]:
    try:
        n = int(round(float(v)))
        return max(1, min(5, n))
    except (TypeError, ValueError):
        return None


def _clean_side(raw: dict, metrics: list) -> dict:
    out: Dict[str, Any] = {}
    for m in metrics:
        score = _to_int_1_5(raw.get(m))
        if score is not None:
            out[m] = score
    if raw.get("comment"):
        out["comment"] = str(raw["comment"])[:1000]
    scores = [out[m] for m in metrics if m in out]
    if scores:
        out["overall_score"] = round(sum(scores) / len(scores), 2)
    return out


def run_image_evaluation(job_id: str) -> None:
    """Run the multimodal pairwise image judge for one image job."""
    db = _get_firestore_client()
    doc_ref = db.collection(IMAGE_COLLECTION).document(job_id)
    snap = doc_ref.get()
    if not snap.exists:
        raise RuntimeError(f"Image job {job_id} not found")
    job = snap.to_dict() or {}

    doc_ref.update({"auto_eval_status": "running"})

    results = job.get("results") or {}
    side_map = job.get("side_map") or {}
    is_i2i = str(job.get("mode") or "t2i").lower() == "i2i"
    metrics = _metrics_for(is_i2i)

    a_url = _result_url(results.get("A"))
    b_url = _result_url(results.get("B"))

    # Need both sides to render a fair pairwise verdict.
    if not (a_url and b_url):
        doc_ref.update({
            "auto_eval_status": "error",
            "auto_eval_error": "One or both image sides missing — cannot evaluate.",
        })
        return

    try:
        a_bytes = download_blob_to_bytes(normalize_gcs_url(a_url))
        b_bytes = download_blob_to_bytes(normalize_gcs_url(b_url))

        contents = [
            _build_prompt(job, is_i2i),
            "IMAGE A:",
            types.Part.from_bytes(data=a_bytes, mime_type=_image_mime(a_url)),
            "IMAGE B:",
            types.Part.from_bytes(data=b_bytes, mime_type=_image_mime(b_url)),
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

        side_a = _clean_side(parsed.get("A") or {}, metrics)
        side_b = _clean_side(parsed.get("B") or {}, metrics)
        winner_label = str(parsed.get("winner") or "").strip().upper()
        winner_engine = side_map.get(winner_label) if winner_label in ("A", "B") else None

        ai_eval = {
            "model": EVAL_MODEL,
            "evaluated_at": time.time(),
            "metrics": metrics,
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
