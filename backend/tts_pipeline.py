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

# --- Voice tag taxonomy -----------------------------------------------------
# Voices are tagged along two axes: LANGUAGE (derived from the detected BCP-47
# code) and INDUSTRY / use-case (classified from the script). The industry list
# is a fixed, curated set of < 20 tags. Both feed the shared `categories` field
# so the same tags surface in human eval, AI evals, and analytics.
VOICE_INDUSTRIES = [
    "📞 Customer Service", "📣 Advertising", "📚 Education", "🎮 Gaming",
    "🎬 Entertainment", "📰 News & Media", "🏥 Healthcare", "💰 Finance",
    "🛍️ Retail & E-commerce", "✈️ Travel & Hospitality", "🚗 Automotive",
    "🍔 Food & Beverage", "💻 Technology", "🏛️ Government", "📖 Audiobook",
    "🧘 Wellness", "⚖️ Legal", "🏠 Real Estate", "📱 Telecom",
]  # 19 tags

LANG_DISPLAY = {
    "en": "🇬🇧 English", "hi": "🇮🇳 Hindi", "zh": "🇨🇳 Chinese", "ta": "🇮🇳 Tamil",
    "te": "🇮🇳 Telugu", "ja": "🇯🇵 Japanese", "ko": "🇰🇷 Korean", "id": "🇮🇩 Indonesian",
    "th": "🇹🇭 Thai", "vi": "🇻🇳 Vietnamese", "ms": "🇲🇾 Malay", "fil": "🇵🇭 Filipino",
    "es": "🇪🇸 Spanish", "fr": "🇫🇷 French", "de": "🇩🇪 German", "pt": "🇵🇹 Portuguese",
    "ar": "🌐 Arabic", "bn": "🇧🇩 Bengali", "ur": "🇵🇰 Urdu", "ru": "🇷🇺 Russian",
    "it": "🇮🇹 Italian", "gu": "🇮🇳 Gujarati", "kn": "🇮🇳 Kannada", "ml": "🇮🇳 Malayalam",
    "mr": "🇮🇳 Marathi", "pa": "🇮🇳 Punjabi",
}


def _language_tags(code: str) -> List[str]:
    """Map a BCP-47 (or mixed e.g. 'hi-en') code to display language tag(s)."""
    c = (code or "").strip().lower()
    if not c:
        return []
    out: List[str] = []
    for p in c.split("-"):
        p = p.strip()
        if not p:
            continue
        tag = LANG_DISPLAY.get(p, f"🌐 {p.upper()}")
        if tag not in out:
            out.append(tag)
    return out


def _classify_industry(text: str) -> List[str]:
    """Pick the 1-2 best-fitting industry tags from the fixed list via gemini."""
    text = (text or "").strip()
    if not text:
        return []
    try:
        from google import genai
        client = genai.Client(vertexai=True, project=GCP_PROJECT_ID, location="global")
        lst = ", ".join(VOICE_INDUSTRIES)
        r = client.models.generate_content(
            model=LANG_TAGGER_MODEL,
            contents=(
                "You are a tagging system for voice-over / TTS scripts. From this "
                f"fixed list:\n{lst}\n\n"
                "Pick the 1-2 tags that best describe the script's industry / use-case.\n"
                "Return ONLY the tags exactly as written above, comma-separated, "
                "nothing else.\n\n"
                f"Script: {text[:800]}"
            ),
        )
        raw = (getattr(r, "text", "") or "").strip()
        picks = [t.strip() for t in raw.split(",") if t.strip()]
        valid = [t for t in picks if t in VOICE_INDUSTRIES]
        return valid[:2]
    except Exception as e:
        print(f"[tts_pipeline] industry classify failed: {e}")
        return []


def _voice_categories(text: str, lang_code: str) -> List[str]:
    """Combined language + industry tags for a voice job."""
    return _language_tags(lang_code) + _classify_industry(text)


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


def _local_language(code: Optional[str]) -> Optional[str]:
    """For a mixed/code-switched tag (e.g. hi-en, en-hi), route GENERATION to the
    local language — the non-English component (hi). Single codes pass through.
    The full mixed tag is still stored on the job for display/filtering."""
    c = (code or "").strip().lower()
    if "-" not in c:
        return c or None
    parts = [p for p in c.split("-") if p]
    for p in parts:           # prefer the first non-English (local) language
        if p != "en":
            return p
    return parts[0] if parts else (c or None)


# --- generation: one engine -------------------------------------------------

async def _gen_gemini(case: dict) -> dict:
    return await generate_gemini_tts(
        text=case.get("text", "") or "",
        voice=case.get("voice", "Kore"),
        style_prompt=case.get("style_prompt"),
        speakers=_speakers(case),
        language=_local_language(case.get("language")),
        case_id=case.get("id", "case"),
    )


async def _gen_eleven(case: dict) -> dict:
    # ElevenLabs-specific voice override (`el_voice`) wins so Gemini keeps its own
    # `voice`; else fall back to the shared voice / first speaker. Native-language
    # voice still applies when el_voice/voice don't map (see _resolve_voice).
    voice = case.get("el_voice") or case.get("voice", "Rachel")
    speakers = _speakers(case)
    if speakers and not case.get("el_voice"):
        voice = speakers[0].get("voice", voice)
    return await generate_elevenlabs_tts(
        text=case.get("text", "") or "",
        voice=voice,
        style_prompt=case.get("style_prompt"),
        speakers=speakers,
        language=_local_language(case.get("language")),
        case_id=case.get("id", "case"),
    )


# Engine dispatch. The two shipped engines are wired statically so this module
# stands alone; any other engine is resolved through the model registry, so
# adding a TTS model is a registry entry plus one generator here.
_GEN_BY_PROVIDER = {
    "gemini_tts": _gen_gemini,
    "elevenlabs": _gen_eleven,
}
_PROVIDER_BY_ENGINE = {
    ENGINE_GEMINI: "gemini_tts",
    ENGINE_ELEVEN: "elevenlabs",
}


def _provider_for_engine(engine: str) -> Optional[str]:
    provider = _PROVIDER_BY_ENGINE.get(engine)
    if provider:
        return provider
    try:
        import main  # lazy: main imports this module's callers at boot
        spec = main.registry.models.get(engine)
        return spec.provider if spec else None
    except Exception:
        return None


async def _gen_for_engine(engine: str, case: dict) -> dict:
    """Generate one side by engine id. Never raises — an unknown engine comes
    back as an error result so the other side still lands."""
    gen = _GEN_BY_PROVIDER.get(_provider_for_engine(engine) or "")
    if gen is None:
        return {"model": ENGINE_LABELS.get(engine, engine), "status": "error",
                "error": f"No TTS generator for engine '{engine}'"}
    return await gen(case)


# --- Firestore job lifecycle -----------------------------------------------

def build_tts_job_doc(
    case: dict,
    engines: List[str],
    batch_id: Optional[str] = None,
    results: Optional[Dict[str, dict]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> dict:
    """Build (but don't write) a tts_jobs doc for a given pair of engines.

    Which engine is the "A" side is randomized so blind human voting is
    unbiased; `side_map` records the truth. Mutates `case["language"]` with the
    autodetected code so both engines get the hint during generation.

    `results` overrides the default "generating" placeholders — the ingest path
    passes ready-made success results.
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

    # Auto-tag the voice (language + industry) when no categories were supplied.
    provided_cats = _categories(case)
    categories = provided_cats if provided_cats else _voice_categories(case.get("text", ""), lang)

    shuffled = list(engines)
    random.shuffle(shuffled)
    side_map = {"A": shuffled[0], "B": shuffled[1]}

    if results is None:
        results = {
            "A": {"status": "generating", "engine": side_map["A"]},
            "B": {"status": "generating", "engine": side_map["B"]},
        }

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
        "categories": categories,
        "style_prompt": case.get("style_prompt", ""),
        "mode": _mode(case),
        "voice": case.get("voice", ""),
        "speakers": _speakers(case) or [],
        "language": lang,
        "language_autodetected": autodetected,
        "timestamp": time.time(),
        "side_map": side_map,
        "results": results,
        "auto_eval_status": "pending",
    }
    if extra:
        doc.update(extra)
    return doc


def create_tts_job_with_engines(
    case: dict, engines: List[str], batch_id: Optional[str] = None,
    run_eval: bool = True,
) -> str:
    """Create a TTS job for an explicitly named pair of engines (used by
    `/api/tts/prompts`). `process_tts_job` reads `side_map`, so these run
    exactly like the default Gemini-vs-ElevenLabs pairing."""
    if len(engines) != 2:
        raise ValueError(f"TTS duels are two-sided: got {len(engines)} engine(s)")
    doc = build_tts_job_doc(
        case, engines, batch_id=batch_id,
        extra=None if run_eval else {"auto_eval_status": "skipped"},
    )
    db = _get_firestore_client()
    db.collection(TTS_COLLECTION).document(doc["id"]).set(doc)
    return doc["id"]


def create_tts_job(case: dict, batch_id: Optional[str] = None) -> str:
    """Create the Firestore tts_jobs doc for the default Gemini-vs-ElevenLabs
    pairing, with a randomized blind A/B side_map. Returns the job_id."""
    doc = build_tts_job_doc(case, [ENGINE_GEMINI, ENGINE_ELEVEN], batch_id=batch_id)
    db = _get_firestore_client()
    db.collection(TTS_COLLECTION).document(doc["id"]).set(doc)
    return doc["id"]


async def process_tts_job(job_id: str, case: dict) -> str:
    """Generate on both of the job's engines in parallel, store under its blind
    A/B labels per side_map, then run the AI audio judge. Returns job_id."""
    db = _get_firestore_client()
    snap = db.collection(TTS_COLLECTION).document(job_id).get()
    if not snap.exists:
        raise RuntimeError(f"TTS job {job_id} not found")
    job = snap.to_dict() or {}
    side_map = job.get("side_map") or {"A": ENGINE_GEMINI, "B": ENGINE_ELEVEN}

    labels = ("A", "B")
    results = await asyncio.gather(
        *[_gen_for_engine(side_map[label], case) for label in labels],
        return_exceptions=True,
    )

    update: Dict[str, Any] = {}
    for label, res in zip(labels, results):
        engine = side_map[label]
        if isinstance(res, Exception):
            res = {"model": ENGINE_LABELS.get(engine, engine), "status": "error",
                   "error": str(res)}
        res = dict(res)
        res["engine"] = engine
        update[f"results.{label}"] = res
    db.collection(TTS_COLLECTION).document(job_id).update(update)

    # `run_eval: false` on an intake request writes auto_eval_status "skipped".
    if job.get("auto_eval_status") == "skipped":
        return job_id

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
        newr = dict(await _gen_for_engine(engine, case))
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
