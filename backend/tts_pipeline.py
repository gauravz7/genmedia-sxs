"""TTS side-by-side (SxS) auto-evaluation pipeline.

Mirrors `sxs_pipeline.py` but for audio. For a single case this module:
  1. Generates speech on BOTH Gemini 3.1 Flash TTS and ElevenLabs in parallel.
  2. Persists both WAV/mp3 outputs to GCS (handled inside the providers).
  3. Writes / patches a Firestore job doc in the `tts_jobs` collection, with the
     two engine results stored under BLIND labels "A" and "B". The truth (which
     label is which engine) lives in `side_map` so the voting UI stays blind.
  4. Runs the multimodal-audio AI judge (tts_evaluator.run_tts_evaluation).

A/B is randomized per job so blind human voting is unbiased.

No module-level network calls — clients are constructed lazily.
"""

import asyncio
import os
import random
import re
import time
from typing import Any, Dict, List, Optional

from providers.gemini_tts_provider import generate_gemini_tts, MODEL_LABEL as GEMINI_LABEL
from providers.elevenlabs_provider import generate_elevenlabs_tts, MODEL_LABEL as ELEVEN_LABEL

# Isolated collections — TTS lives entirely apart from the video SxS flow.
TTS_COLLECTION = os.getenv("TTS_COLLECTION", "tts_jobs")
TTS_VOTES_COLLECTION = os.getenv("TTS_VOTES_COLLECTION", "tts_votes")
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "vital-octagon-19612")

# Stable engine identifiers (used in side_map + leaderboard).
ENGINE_GEMINI = "gemini-3.1-flash-tts-preview"
ENGINE_ELEVEN = "elevenlabs-v3"

ENGINE_LABELS = {ENGINE_GEMINI: GEMINI_LABEL, ENGINE_ELEVEN: ELEVEN_LABEL}


def _slug(value: Any) -> str:
    s = str(value) if value is not None else "case"
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s or "case"


def _get_firestore_client():
    from google.cloud import firestore
    return firestore.Client(project=GCP_PROJECT_ID)


def _mode(case: dict) -> str:
    return str(case.get("mode") or "single").strip().lower()


def _categories(case: dict) -> List[str]:
    raw = case.get("categories") or case.get("tags") or case.get("category") or []
    if isinstance(raw, str):
        raw = [raw]
    return [str(c).strip() for c in raw if str(c).strip()]


LANG_TAGGER_MODEL = os.getenv("LANG_TAGGER_MODEL", "gemini-3.5-flash")


def _detect_language(text: str) -> str:
    """Auto-tag the language of a transcript with gemini-3.5-flash. Returns a
    lowercase BCP-47 code, or a hyphenated mixed code (dominant first, e.g.
    'hi-en' for Hinglish) when two languages are substantially mixed. Returns ""
    on failure (the TTS engines still auto-detect at synthesis time)."""
    text = (text or "").strip()
    if not text:
        return ""
    try:
        from google import genai
        client = genai.Client(vertexai=True, project=GCP_PROJECT_ID, location="global")
        r = client.models.generate_content(
            model=LANG_TAGGER_MODEL,
            contents=(
                "You are a language identifier. Identify the language of the text below "
                "and respond with ONLY a lowercase BCP-47 code — no other words.\n"
                "- Single language: one code (e.g. en, ja, zh, ko, fr, hi, es).\n"
                "- If two languages are substantially mixed / code-switched (e.g. Hinglish "
                "= Hindi + English), return both codes joined by a hyphen, dominant first "
                "(e.g. hi-en, en-es).\n\n"
                f"Text: {text[:800]}"
            ),
        )
        code = (getattr(r, "text", "") or "").strip().split()[0].lower()
        code = re.sub(r"[^a-z-]", "", code)[:12].strip("-")
        return code
    except Exception:
        return ""


def _speakers(case: dict) -> Optional[List[dict]]:
    sp = case.get("speakers")
    if isinstance(sp, list) and sp:
        return sp
    return None


# --- generation: one engine -------------------------------------------------

async def _gen_gemini(case: dict) -> dict:
    return await generate_gemini_tts(
        text=case.get("text", "") or "",
        voice=case.get("voice", "Kore"),
        style_prompt=case.get("style_prompt"),
        speakers=_speakers(case),
        language=case.get("language"),
        case_id=case.get("id", "case"),
    )


async def _gen_eleven(case: dict) -> dict:
    # ElevenLabs is single-voice; use the case voice (mapped) or first speaker.
    voice = case.get("voice", "Rachel")
    speakers = _speakers(case)
    if speakers:
        voice = speakers[0].get("voice", voice)
    return await generate_elevenlabs_tts(
        text=case.get("text", "") or "",
        voice=voice,
        style_prompt=case.get("style_prompt"),
        speakers=speakers,
        language=case.get("language"),
        case_id=case.get("id", "case"),
    )


# --- Firestore job lifecycle -----------------------------------------------

def create_tts_job(case: dict, batch_id: Optional[str] = None) -> str:
    """Create the Firestore tts_jobs doc with a randomized blind A/B side_map.

    Returns the job_id.
    """
    case_id = case.get("id", "case")
    job_id = f"tts_{_slug(case_id)}_{int(time.time()*1000)}_{random.randint(100,999)}"

    # Auto-tag language when not supplied, and feed it back into the case so both
    # engines receive the hint during generation.
    provided_lang = (case.get("language") or "").strip()
    autodetected = False
    if provided_lang:
        lang = provided_lang
    else:
        lang = _detect_language(case.get("text", ""))
        autodetected = bool(lang)
        if lang:
            case["language"] = lang

    # Randomize which engine is the "A" side for blind voting.
    engines = [ENGINE_GEMINI, ENGINE_ELEVEN]
    random.shuffle(engines)
    side_map = {"A": engines[0], "B": engines[1]}

    doc = {
        "id": job_id,
        "source": "sxs_auto",
        "media_type": "audio",
        "modality": "audio",
        "batch_id": batch_id,
        "customer": case.get("customer", ""),
        "prompt_id": case_id,
        "text": case.get("text", ""),
        "prompt": case.get("text", ""),  # alias so generic UIs can read .prompt
        "categories": _categories(case),
        "style_prompt": case.get("style_prompt", ""),
        "mode": _mode(case),
        "voice": case.get("voice", ""),
        "speakers": _speakers(case) or [],
        "language": lang,
        "language_autodetected": autodetected,
        "timestamp": time.time(),
        "side_map": side_map,
        "results": {
            "A": {"status": "generating", "engine": side_map["A"]},
            "B": {"status": "generating", "engine": side_map["B"]},
        },
        "auto_eval_status": "pending",
    }

    db = _get_firestore_client()
    db.collection(TTS_COLLECTION).document(job_id).set(doc)
    return job_id


async def process_tts_job(job_id: str, case: dict) -> str:
    """Generate on both engines in parallel, store under the job's blind A/B
    labels per its side_map, then run the AI audio judge. Returns job_id."""
    db = _get_firestore_client()
    snap = db.collection(TTS_COLLECTION).document(job_id).get()
    if not snap.exists:
        raise RuntimeError(f"TTS job {job_id} not found")
    job = snap.to_dict() or {}
    side_map = job.get("side_map") or {"A": ENGINE_GEMINI, "B": ENGINE_ELEVEN}

    gemini_res, eleven_res = await asyncio.gather(
        _gen_gemini(case),
        _gen_eleven(case),
        return_exceptions=True,
    )

    if isinstance(gemini_res, Exception):
        gemini_res = {"model": GEMINI_LABEL, "status": "error", "error": str(gemini_res)}
    if isinstance(eleven_res, Exception):
        eleven_res = {"model": ELEVEN_LABEL, "status": "error", "error": str(eleven_res)}

    by_engine = {ENGINE_GEMINI: gemini_res, ENGINE_ELEVEN: eleven_res}

    update: Dict[str, Any] = {}
    for label in ("A", "B"):
        engine = side_map[label]
        res = dict(by_engine[engine])
        res["engine"] = engine
        update[f"results.{label}"] = res
    db.collection(TTS_COLLECTION).document(job_id).update(update)

    try:
        from tts_evaluator import run_tts_evaluation
        run_tts_evaluation(job_id)
    except Exception as e:  # pragma: no cover
        print(f"[tts_pipeline] AI eval failed for {job_id}: {e}")
        try:
            db.collection(TTS_COLLECTION).document(job_id).update(
                {"auto_eval_status": "error", "auto_eval_error": str(e)}
            )
        except Exception:
            pass

    return job_id


async def run_tts_case(case: dict, batch_id: Optional[str] = None) -> str:
    job_id = create_tts_job(case, batch_id=batch_id)
    return await process_tts_job(job_id, case)


def _case_from_job(job: dict) -> dict:
    """Reconstruct a case dict from a stored job (for retries)."""
    return {
        "id": job.get("prompt_id"),
        "customer": job.get("customer"),
        "text": job.get("text"),
        "style_prompt": job.get("style_prompt"),
        "mode": job.get("mode"),
        "voice": job.get("voice"),
        "speakers": job.get("speakers") or None,
        "language": job.get("language"),
    }


async def retry_tts_job(job_id: str) -> dict:
    """Re-generate ONLY the failed side(s) of an existing job, then re-eval."""
    db = _get_firestore_client()
    snap = db.collection(TTS_COLLECTION).document(job_id).get()
    if not snap.exists:
        return {"job_id": job_id, "status": "not_found"}
    job = snap.to_dict() or {}
    case = _case_from_job(job)
    side_map = job.get("side_map") or {"A": ENGINE_GEMINI, "B": ENGINE_ELEVEN}
    results = job.get("results") or {}

    retried = []
    for label in ("A", "B"):
        res = results.get(label) or {}
        if isinstance(res, dict) and res.get("status") == "success":
            continue
        engine = side_map.get(label, ENGINE_GEMINI)
        newr = await (_gen_gemini(case) if engine == ENGINE_GEMINI else _gen_eleven(case))
        newr = dict(newr)
        newr["engine"] = engine
        db.collection(TTS_COLLECTION).document(job_id).update({f"results.{label}": newr})
        retried.append({"side": label, "engine": engine, "status": newr.get("status"), "error": newr.get("error", "")})

    db.collection(TTS_COLLECTION).document(job_id).update({"auto_eval_status": "pending"})
    try:
        from tts_evaluator import run_tts_evaluation
        run_tts_evaluation(job_id)
    except Exception as e:  # pragma: no cover
        db.collection(TTS_COLLECTION).document(job_id).update(
            {"auto_eval_status": "error", "auto_eval_error": str(e)}
        )
    return {"job_id": job_id, "retried": retried}


async def process_tts_batch(pairs: List[tuple]) -> List[str]:
    """Process a list of (job_id, case) pairs already created.

    Concurrency capped at 2 cases at a time (each case fans out to 2 engines).
    """
    sem = asyncio.Semaphore(int(os.getenv("TTS_CONCURRENCY", "3")))

    async def _run(job_id: str, case: dict):
        async with sem:
            try:
                return await process_tts_job(job_id, case)
            except Exception as e:  # pragma: no cover
                print(f"[tts_pipeline] process_tts_job failed {job_id}: {e}")
                return job_id

    return await asyncio.gather(*[_run(jid, c) for jid, c in pairs])


async def run_tts_batch(cases: list) -> List[str]:
    """Create + process + eval all cases. Returns job_ids."""
    pairs = [(create_tts_job(c), c) for c in cases]
    await process_tts_batch(pairs)
    return [jid for jid, _ in pairs]
