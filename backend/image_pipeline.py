"""Image side-by-side (SxS) auto-evaluation pipeline.

Mirrors `sxs_pipeline.py` / `tts_pipeline.py`. For a single case this module:
  1. Resolves the case's matchup (a fixed Gemini-image vs GPT-image pair).
  2. Generates BOTH sides in parallel (asyncio.gather): T2I or I2I depending on
     the case mode.
  3. Persists both images to GCS (handled inside the providers, under `images/`).
  4. Writes / patches a Firestore job doc in the `image_jobs` collection. The two
     model results are stored under BLIND labels "A" and "B"; the truth (which
     label is which model) lives in `side_map` so the voting UI stays blind. The
     full model identity (incl. GPT quality tier) is also stored for admin under
     each result's `engine` field.
  5. Runs the multimodal image AI judge (image_evaluator.run_image_evaluation).

Case schema:
    {id, mode: "t2i"|"i2i", prompt, input_image?, matchup?}

Matchup registry (default 3 fixed pairs; case picks via case["matchup"],
default = matchup #1):
    1: gemini-3.1-flash-image vs gpt-image-1 (medium)
    2: gemini-3-pro-image     vs gpt-image-1 (high)
    3: instant-ramen          vs gpt-image-1 (low)

No module-level network calls — clients are constructed lazily.
"""

import asyncio
import os
import random
import re
import time
from typing import Any, Dict, List, Optional

from providers.gemini_image_provider import generate_gemini_image
from providers.gpt_image_provider import generate_gpt_image, GPT_IMAGE_MODEL

# Isolated collections — image SxS lives entirely apart from the video flow.
IMAGE_COLLECTION = os.getenv("IMAGE_COLLECTION", "image_jobs")
IMAGE_VOTES_COLLECTION = os.getenv("IMAGE_VOTES_COLLECTION", "image_votes")
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "vital-octagon-19612")


# --- Matchup registry -------------------------------------------------------
# Each side is a dict: {"engine": <stable id>, "provider": "gemini"|"gpt",
#   "model": <model id passed to provider>, "quality": <gpt tier or None>}.
def _gemini_side(model: str) -> dict:
    return {"engine": model, "provider": "gemini", "model": model, "quality": None}


def _gpt_side(quality: str) -> dict:
    return {
        "engine": f"{GPT_IMAGE_MODEL}-{quality}",
        "provider": "gpt",
        "model": GPT_IMAGE_MODEL,
        "quality": quality,
    }


MATCHUPS: Dict[str, dict] = {
    "gemini-3.1-flash-image_vs_gpt2-medium": {
        "id": "gemini-3.1-flash-image_vs_gpt2-medium",
        "label": "Gemini 3.1 Flash Image vs GPT-image (medium)",
        "left": _gemini_side("gemini-3.1-flash-image"),
        "right": _gpt_side("medium"),
    },
    "gemini-3-pro-image_vs_gpt2-high": {
        "id": "gemini-3-pro-image_vs_gpt2-high",
        "label": "Gemini 3 Pro Image vs GPT-image (high)",
        "left": _gemini_side("gemini-3-pro-image"),
        "right": _gpt_side("high"),
    },
    "instant-ramen_vs_gpt2-low": {
        "id": "instant-ramen_vs_gpt2-low",
        "label": "Instant Ramen vs GPT-image (low)",
        "left": _gemini_side("instant-ramen"),
        "right": _gpt_side("low"),
    },
}

DEFAULT_MATCHUP = "gemini-3.1-flash-image_vs_gpt2-medium"


def list_matchups() -> List[dict]:
    """Public registry view (id + label + side identities) for the admin UI."""
    return [
        {
            "id": m["id"],
            "label": m["label"],
            "left": m["left"]["engine"],
            "right": m["right"]["engine"],
        }
        for m in MATCHUPS.values()
    ]


def resolve_matchup(case: dict) -> dict:
    key = (case.get("matchup") or "").strip()
    return MATCHUPS.get(key, MATCHUPS[DEFAULT_MATCHUP])


# --- small helpers ----------------------------------------------------------

def _slug(value: Any) -> str:
    s = str(value) if value is not None else "case"
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s or "case"


def _get_firestore_client():
    from google.cloud import firestore
    return firestore.Client(project=GCP_PROJECT_ID)


def _mode(case: dict) -> str:
    # Accept both `mode` and `modality` as the t2i/i2i selector.
    m = str(case.get("mode") or case.get("modality") or "t2i").strip().lower()
    return "i2i" if m in ("i2i", "edit", "image-to-image") else "t2i"


def _categories(case: dict) -> List[str]:
    """Normalize a case's tags/categories from any of the accepted keys."""
    raw = case.get("categories") or case.get("tags") or case.get("category") or []
    if isinstance(raw, str):
        raw = [raw]
    return [str(c).strip() for c in raw if str(c).strip()]


def _input_image(case: dict) -> Optional[str]:
    # Accept a single `input_image`/`reference_image`, or the first of an
    # `input_images` array (the external eval-sheet schema).
    single = case.get("input_image") or case.get("reference_image")
    if single:
        return single
    arr = case.get("input_images")
    if isinstance(arr, list) and arr:
        return arr[0]
    return None


# --- generation: one side ---------------------------------------------------

def _aspect_ratio(case: dict) -> Optional[str]:
    return str(case.get("aspect_ratio") or case.get("aspectRatio") or "").strip() or None


def _resolution(case: dict) -> Optional[str]:
    return str(case.get("resolution") or "").strip() or None


async def _gen_side(side: dict, case: dict) -> dict:
    """Generate one matchup side for a case. Routes by provider. Captures any
    error into the result dict (never raises)."""
    mode = _mode(case)
    prompt = case.get("prompt", "") or ""
    input_image = _input_image(case) if mode == "i2i" else None
    case_id = case.get("id", "case")
    aspect_ratio = _aspect_ratio(case)
    resolution = _resolution(case)

    if side["provider"] == "gemini":
        return await generate_gemini_image(
            model=side["model"], prompt=prompt,
            input_image_url=input_image, case_id=case_id,
            aspect_ratio=aspect_ratio, resolution=resolution,
        )
    if side["provider"] == "gpt":
        return await generate_gpt_image(
            prompt=prompt, quality=side.get("quality") or "medium",
            input_image_url=input_image, case_id=case_id,
            aspect_ratio=aspect_ratio, resolution=resolution,
        )
    return {"model": side.get("engine", "unknown"), "status": "error",
            "error": f"Unknown provider: {side['provider']}"}


# --- Firestore job lifecycle ------------------------------------------------

def create_image_job(case: dict, batch_id: Optional[str] = None) -> str:
    """Create the Firestore image_jobs doc with a randomized blind A/B side_map.

    Returns the job_id. The two matchup sides are randomly assigned to labels
    A/B so blind human voting is unbiased; `side_map` records the truth.
    """
    case_id = case.get("id", "case")
    job_id = f"img_{_slug(case_id)}_{int(time.time()*1000)}_{random.randint(100,999)}"

    matchup = resolve_matchup(case)
    sides = [matchup["left"], matchup["right"]]
    random.shuffle(sides)
    side_a, side_b = sides[0], sides[1]
    side_map = {"A": side_a["engine"], "B": side_b["engine"]}

    doc = {
        "id": job_id,
        "source": "sxs_auto",
        "media_type": "image",
        "modality": "image",
        "batch_id": batch_id,
        "customer": case.get("customer", ""),
        "prompt_id": case_id,
        "prompt": case.get("prompt", ""),
        "categories": _categories(case),
        "aspect_ratio": _aspect_ratio(case) or "",
        "resolution": _resolution(case) or "",
        "mode": _mode(case),
        "matchup": matchup["id"],
        "matchup_label": matchup["label"],
        "input_image": _input_image(case) or "",
        "timestamp": time.time(),
        "side_map": side_map,
        # Full identity (provider/model/quality) per side — for admin + retry.
        "side_specs": {"A": side_a, "B": side_b},
        "results": {
            "A": {"status": "generating", "engine": side_a["engine"]},
            "B": {"status": "generating", "engine": side_b["engine"]},
        },
        "auto_eval_status": "pending",
    }

    db = _get_firestore_client()
    db.collection(IMAGE_COLLECTION).document(job_id).set(doc)
    return job_id


async def process_job(job_id: str, case: dict) -> str:
    """Generate both matchup sides concurrently, store under the job's blind A/B
    labels per its side_specs, then run the AI image judge. Returns job_id."""
    db = _get_firestore_client()
    snap = db.collection(IMAGE_COLLECTION).document(job_id).get()
    if not snap.exists:
        raise RuntimeError(f"Image job {job_id} not found")
    job = snap.to_dict() or {}
    side_specs = job.get("side_specs") or {}
    side_a = side_specs.get("A") or resolve_matchup(case)["left"]
    side_b = side_specs.get("B") or resolve_matchup(case)["right"]

    res_a, res_b = await asyncio.gather(
        _gen_side(side_a, case),
        _gen_side(side_b, case),
        return_exceptions=True,
    )

    if isinstance(res_a, Exception):
        res_a = {"model": side_a.get("engine"), "status": "error", "error": str(res_a)}
    if isinstance(res_b, Exception):
        res_b = {"model": side_b.get("engine"), "status": "error", "error": str(res_b)}

    update: Dict[str, Any] = {}
    for label, res, side in (("A", res_a, side_a), ("B", res_b, side_b)):
        r = dict(res)
        r["engine"] = side.get("engine")
        update[f"results.{label}"] = r
    db.collection(IMAGE_COLLECTION).document(job_id).update(update)

    try:
        from image_evaluator import run_image_evaluation
        run_image_evaluation(job_id)
    except Exception as e:  # pragma: no cover
        print(f"[image_pipeline] AI eval failed for {job_id}: {e}")
        try:
            db.collection(IMAGE_COLLECTION).document(job_id).update(
                {"auto_eval_status": "error", "auto_eval_error": str(e)}
            )
        except Exception:
            pass

    return job_id


async def run_image_case(case: dict, batch_id: Optional[str] = None) -> str:
    job_id = create_image_job(case, batch_id=batch_id)
    return await process_job(job_id, case)


def _case_from_job(job: dict) -> dict:
    """Reconstruct a case dict from a stored job (for retries)."""
    return {
        "id": job.get("prompt_id"),
        "customer": job.get("customer"),
        "prompt": job.get("prompt"),
        "mode": job.get("mode"),
        "input_image": job.get("input_image") or None,
        "matchup": job.get("matchup"),
    }


async def retry_job(job_id: str) -> dict:
    """Re-generate ONLY the failed side(s) of an existing job, then re-eval."""
    db = _get_firestore_client()
    snap = db.collection(IMAGE_COLLECTION).document(job_id).get()
    if not snap.exists:
        return {"job_id": job_id, "status": "not_found"}
    job = snap.to_dict() or {}
    case = _case_from_job(job)
    side_specs = job.get("side_specs") or {}
    matchup = resolve_matchup(case)
    side_specs.setdefault("A", matchup["left"])
    side_specs.setdefault("B", matchup["right"])
    results = job.get("results") or {}

    retried = []
    for label in ("A", "B"):
        res = results.get(label) or {}
        if isinstance(res, dict) and res.get("status") == "success":
            continue
        side = side_specs[label]
        newr = await _gen_side(side, case)
        newr = dict(newr)
        newr["engine"] = side.get("engine")
        db.collection(IMAGE_COLLECTION).document(job_id).update({f"results.{label}": newr})
        retried.append({
            "side": label, "engine": side.get("engine"),
            "status": newr.get("status"), "error": newr.get("error", ""),
        })

    db.collection(IMAGE_COLLECTION).document(job_id).update({"auto_eval_status": "pending"})
    try:
        from image_evaluator import run_image_evaluation
        run_image_evaluation(job_id)
    except Exception as e:  # pragma: no cover
        db.collection(IMAGE_COLLECTION).document(job_id).update(
            {"auto_eval_status": "error", "auto_eval_error": str(e)}
        )
    return {"job_id": job_id, "retried": retried}


async def process_batch(pairs: List[tuple]) -> List[str]:
    """Process a list of (job_id, case) pairs already created.

    Concurrency capped at 2 cases at a time (each case fans out to 2 models).
    """
    sem = asyncio.Semaphore(2)

    async def _run(job_id: str, case: dict):
        async with sem:
            try:
                return await process_job(job_id, case)
            except Exception as e:  # pragma: no cover
                print(f"[image_pipeline] process_job failed {job_id}: {e}")
                return job_id

    return await asyncio.gather(*[_run(jid, c) for jid, c in pairs])


async def run_batch(cases: list) -> List[str]:
    """Create + process + eval all cases. Returns job_ids."""
    pairs = [(create_image_job(c), c) for c in cases]
    await process_batch(pairs)
    return [jid for jid, _ in pairs]
