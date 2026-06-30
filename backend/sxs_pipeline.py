"""Side-by-side (SxS) auto-evaluation pipeline.

For a single case this module:
  1. Generates a video on BOTH Seedance 2.0 (via fal) and Gemini Omni
     (bouncybohr, via the Agent Platform / genai Interactions API).
  2. Persists both outputs to GCS.
  3. Writes / patches a Firestore job doc in the `eval_jobs` collection.
  4. Runs the Core-5 auto-eval (video_evaluator_sdk.run_core5_evaluation) on
     both generated videos.

Asset inputs (reference_images / reference_videos) are assumed to already be
GCS https/gs URLs at this point (see util/asset_intake.py). They are pulled to
bytes with `download_blob_to_bytes`.

No module-level network calls — every client is constructed lazily inside the
functions so the module is importable with no side effects.
"""

import asyncio
import base64
import os
import re
import time
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

import fal_client
from google import genai
from google.genai import types

from util.gcs_utils import download_blob_to_bytes, upload_from_bytes


# --- Model identity (must match models.json) -------------------------------

SEEDANCE_KEY = "seedance-2-0-r2v"
SEEDANCE_MODEL_ID = "bytedance/seedance-2.0/reference-to-video"

OMNI_MODEL_ID = "bouncybohr"

# Modality (R2V / I2V / T2V / V2V) -> Omni model key. V2V maps to the r2v key.
_OMNI_KEY_BY_MODALITY = {
    "r2v": "omni-preview-r2v",
    "i2v": "omni-preview-i2v",
    "t2v": "omni-preview-t2v",
    "v2v": "omni-preview-r2v",
}

# Isolated test database: SxS jobs live in their own collection, NOT the shared
# production `eval_jobs`. Override with env SXS_COLLECTION if needed.
EVAL_COLLECTION = os.getenv("SXS_COLLECTION", "sxs_jobs")
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "vital-octagon-19612")
OMNI_PROJECT = os.getenv("OMNI_PROJECT", "cloud-llm-preview1")
AUTO_EVAL_MODEL_NAME = "gemini-3.5-flash"


# --- small helpers ---------------------------------------------------------

def _modality(case: dict) -> str:
    m = (case.get("modality") or case.get("type") or "t2v")
    return str(m).strip().lower()


def _omni_key(case: dict) -> str:
    # Classify via the same rules used for admin model selection (FLF2V->i2v, etc.).
    return {"t2v": "omni-preview-t2v", "i2v": "omni-preview-i2v", "r2v": "omni-preview-r2v"}[
        case_model_type(case)
    ]


def _image_mime(url: str) -> str:
    ext = url.split("?")[0].split(".")[-1].lower()
    if ext in ("jpg", "jpeg"):
        return "image/jpeg"
    if ext == "webp":
        return "image/webp"
    if ext == "gif":
        return "image/gif"
    return "image/png"


def _filename_from_url(url: str) -> str:
    base = os.path.basename(url.split("?")[0]) or "asset"
    # fal_client.upload requires ASCII filenames; unicode names (e.g. 图片1.png)
    # raise "'ascii' codec can't encode". Sanitize to an ASCII-safe name while
    # preserving the extension.
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    if not safe.strip("._-"):
        ext = base.rpartition(".")[2]
        safe = f"asset.{ext}" if (ext and ext.isascii()) else "asset.png"
    return safe


def _seedance_duration(case: dict):
    """Coerce case duration to an int in [4, 15], else the literal 'auto'."""
    raw = case.get("duration")
    try:
        val = int(raw)
        if 4 <= val <= 15:
            return val
    except (TypeError, ValueError):
        pass
    return "auto"


def _slug(value: Any) -> str:
    """Slug a (possibly unicode) case id into an ascii-safe token."""
    s = str(value) if value is not None else "case"
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s or "case"


def _get_firestore_client():
    """Lazily build a Firestore client (no module-level network calls)."""
    from google.cloud import firestore
    return firestore.Client(project=GCP_PROJECT_ID)


def _ref_list(case: dict, key: str) -> List[str]:
    vals = case.get(key) or []
    if isinstance(vals, str):
        vals = [vals]
    return [v for v in vals if v]


def _standard_result(model: str, **kwargs) -> dict:
    base = {"model": model}
    base.update(kwargs)
    return base


# --- generation: Seedance 2.0 (fal) ----------------------------------------

async def generate_seedance(case: dict) -> dict:
    """Generate on Seedance 2.0 reference-to-video via fal.

    reference_images / reference_videos are GCS URLs; we download the bytes and
    re-upload to fal's temporary storage so fal can read them reliably. Each
    image/video is referenced in the prompt via @Image{n}: / @Video{n}: tags
    (prepended if not already present).
    """
    start_time = time.time()
    try:
        modified_prompt = case.get("prompt", "") or ""
        case_id = case.get("id", "case")

        image_urls: List[str] = []
        video_urls: List[str] = []
        tag_prefixes: List[str] = []

        # Images -> fal uploads + @Image{n}: tags
        for idx, url in enumerate(_ref_list(case, "reference_images"), start=1):
            data = download_blob_to_bytes(url)
            fal_url = await asyncio.to_thread(
                fal_client.upload,
                data,
                content_type=_image_mime(url),
                file_name=_filename_from_url(url),
            )
            image_urls.append(fal_url)
            tag = f"@Image{idx}:"
            if tag not in modified_prompt:
                tag_prefixes.append(tag)

        # Videos -> fal uploads + @Video{n}: tags
        for idx, url in enumerate(_ref_list(case, "reference_videos"), start=1):
            data = download_blob_to_bytes(url)
            fal_url = await asyncio.to_thread(
                fal_client.upload,
                data,
                content_type="video/mp4",
                file_name=_filename_from_url(url),
            )
            video_urls.append(fal_url)
            tag = f"@Video{idx}:"
            if tag not in modified_prompt:
                tag_prefixes.append(tag)

        if tag_prefixes:
            modified_prompt = f"{' '.join(tag_prefixes)} {modified_prompt}".strip()

        arguments: Dict[str, Any] = {
            "prompt": modified_prompt,
            "resolution": "720p",
            "duration": _seedance_duration(case),
            "aspect_ratio": case.get("aspect_ratio", "auto"),
            "generate_audio": True,
            "bitrate_mode": "standard",
        }
        if image_urls:
            arguments["image_urls"] = image_urls
        if video_urls:
            arguments["video_urls"] = video_urls

        # Prefer the async API when available, otherwise run sync in a thread.
        if hasattr(fal_client, "subscribe_async"):
            result = await fal_client.subscribe_async(
                SEEDANCE_MODEL_ID, arguments=arguments
            )
        else:
            result = await asyncio.to_thread(
                fal_client.subscribe, SEEDANCE_MODEL_ID, arguments=arguments
            )

        video_url = None
        if isinstance(result, dict):
            v = result.get("video")
            if isinstance(v, dict):
                video_url = v.get("url")
            video_url = video_url or result.get("video_url") or result.get("url")
        if not video_url:
            raise RuntimeError("Seedance returned no video URL")

        video_bytes = download_blob_to_bytes(video_url) if (
            video_url.startswith("gs://") or "storage.googleapis.com" in video_url
        ) else _http_get_bytes(video_url)

        ts = int(time.time())
        filename = f"sxs_seedance_{_slug(case_id)}_{ts}.mp4"
        gcs_url = upload_from_bytes(video_bytes, filename, content_type="video/mp4")

        latency = round(time.time() - start_time, 2)
        return _standard_result(
            "Seedance 2.0",
            status="success",
            url=gcs_url,
            latency=latency,
            result={"url": gcs_url, "original_url": video_url},
        )
    except Exception as e:
        return _standard_result(
            "Seedance 2.0",
            status="error",
            error=str(e),
            latency=round(time.time() - start_time, 2),
        )


def _http_get_bytes(url: str) -> bytes:
    import requests
    resp = requests.get(url, timeout=300)
    resp.raise_for_status()
    return resp.content


# --- generation: Gemini Omni (bouncybohr) ----------------------------------

async def generate_omni(case: dict) -> dict:
    """Generate on Gemini Omni via the genai Interactions API."""
    start_time = time.time()
    try:
        client = genai.Client(
            vertexai=True,
            project=OMNI_PROJECT,
            location="global",
            http_options=types.HttpOptions(timeout=600000),  # ms (=10 min)
        )

        inputs: List[Dict[str, Any]] = [
            {"type": "text", "text": case.get("prompt", "") or ""}
        ]

        for url in _ref_list(case, "reference_images"):
            data = download_blob_to_bytes(url)
            b64 = base64.b64encode(data).decode("utf-8")
            inputs.append(
                {"type": "image", "mime_type": _image_mime(url), "data": b64}
            )

        for url in _ref_list(case, "reference_videos"):
            data = download_blob_to_bytes(url)
            b64 = base64.b64encode(data).decode("utf-8")
            inputs.append(
                {"type": "video", "mime_type": "video/mp4", "data": b64}
            )

        interaction = await asyncio.to_thread(
            lambda: client.interactions.create(model=OMNI_MODEL_ID, input=inputs)
        )

        video_bytes = _extract_omni_video_bytes(interaction)
        if not video_bytes:
            raise RuntimeError("Omni returned no video")

        ts = int(time.time())
        filename = f"sxs_omni_{_slug(case.get('id', 'case'))}_{ts}.mp4"
        gcs_url = upload_from_bytes(video_bytes, filename, content_type="video/mp4")

        latency = round(time.time() - start_time, 2)
        return _standard_result(
            "Omni (bouncybohr)",
            status="success",
            url=gcs_url,
            latency=latency,
            result={
                "url": gcs_url,
                "interaction_id": getattr(interaction, "id", None),
            },
        )
    except Exception as e:
        return _standard_result(
            "Omni (bouncybohr)",
            status="error",
            error=str(e),
            latency=round(time.time() - start_time, 2),
        )


def _g(obj, key):
    """Read an attribute from either a dict or a typed object."""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _extract_omni_video_bytes(interaction) -> Optional[bytes]:
    """Pull the first video payload out of an Interactions API response.

    In the installed SDK build, `interaction.steps` are plain dicts shaped like:
        {"type": "thought", "signature": "...", "summary": [...]}
        {"type": "model_output", "content": [
            {"type": "video", "mime_type": "video/mp4", "data": "<base64>"}]}
    so we must read with `.get()` (typed-object access via getattr is also
    supported as a fallback).
    """
    steps = _g(interaction, "steps") or []

    # Preferred: model_output step → video content part.
    for step in steps:
        if _g(step, "type") not in (None, "model_output"):
            continue
        for part in (_g(step, "content") or []):
            data = _g(part, "data")
            if not data:
                continue
            mime = _g(part, "mime_type") or ""
            ptype = _g(part, "type") or ""
            if "video" in mime or ptype == "video":
                try:
                    return base64.b64decode(data)
                except Exception:
                    continue

    # Fallback: first part anywhere that carries base64 data.
    for step in steps:
        for part in (_g(step, "content") or []):
            data = _g(part, "data")
            if data:
                try:
                    return base64.b64decode(data)
                except Exception:
                    continue
    return None


# --- Firestore job lifecycle -----------------------------------------------

def create_sxs_job(case: dict, batch_id: Optional[str] = None) -> str:
    """Create the Firestore eval_jobs doc and return its job_id."""
    case_id = case.get("id", "case")
    job_id = f"sxs_{_slug(case_id)}_{int(time.time()*1000)}"

    omni_key = _omni_key(case)
    doc = {
        "id": job_id,
        "source": "sxs_auto",
        "batch_id": batch_id,
        "customer": case.get("customer", ""),
        "prompt_id": case_id,
        "prompt": case.get("prompt", ""),
        "ratio": case.get("aspect_ratio", "16:9"),
        "modality": _modality(case),
        "duration": case.get("duration"),
        "reference_images": _ref_list(case, "reference_images"),
        "reference_videos": _ref_list(case, "reference_videos"),
        "timestamp": time.time(),
        "results": {
            SEEDANCE_KEY: {"status": "generating"},
            omni_key: {"status": "generating"},
        },
        "auto_eval_status": "pending",
    }

    db = _get_firestore_client()
    db.collection(EVAL_COLLECTION).document(job_id).set(doc)
    return job_id


async def process_job(job_id: str, case: dict) -> str:
    """Generate on both models for an already-created job, patch results, auto-eval.

    Returns the job_id. Robust: a model error is stored as its result dict and
    processing continues.
    """
    omni_key = _omni_key(case)

    # Auto-tag the video case (categories) from its prompt if not already tagged.
    try:
        if not (case.get("categories") or case.get("tags")):
            from providers.vertex_provider import generate_tags_with_gemini
            tags = await generate_tags_with_gemini(
                case.get("prompt", "") or "",
                case.get("start_image_url"),
                case.get("end_image_url"),
                case.get("reference_images"),
            )
            if not tags:  # invalid image -> returns [] -> retry text-only
                tags = await generate_tags_with_gemini(case.get("prompt", "") or "")
            if tags:
                _get_firestore_client().collection(EVAL_COLLECTION).document(job_id).update(
                    {"categories": tags}
                )
    except Exception as e:  # pragma: no cover - tagging is best-effort
        print(f"[sxs] auto-tag failed {job_id}: {e}")

    seedance_res, omni_res = await asyncio.gather(
        generate_seedance(case),
        generate_omni(case),
        return_exceptions=True,
    )

    if isinstance(seedance_res, Exception):
        seedance_res = _standard_result(
            "Seedance 2.0", status="error", error=str(seedance_res)
        )
    if isinstance(omni_res, Exception):
        omni_res = _standard_result(
            "Omni (bouncybohr)", status="error", error=str(omni_res)
        )

    db = _get_firestore_client()
    db.collection(EVAL_COLLECTION).document(job_id).update(
        {
            f"results.{SEEDANCE_KEY}": seedance_res,
            f"results.{omni_key}": omni_res,
        }
    )

    try:
        run_auto_eval(job_id)
    except Exception as e:  # pragma: no cover
        print(f"[sxs_pipeline] auto-eval failed for {job_id}: {e}")
        try:
            db.collection(EVAL_COLLECTION).document(job_id).update(
                {"auto_eval_status": "error", "auto_eval_error": str(e)}
            )
        except Exception:
            pass

    return job_id


async def run_case(case: dict, batch_id: Optional[str] = None) -> str:
    """Create a job then generate + auto-eval it. Returns the job_id."""
    job_id = create_sxs_job(case, batch_id=batch_id)
    return await process_job(job_id, case)


def _case_from_job(job: dict) -> dict:
    """Reconstruct a case dict from a stored job (for retries)."""
    return {
        "id": job.get("prompt_id"),
        "customer": job.get("customer"),
        "prompt": job.get("prompt"),
        "modality": job.get("modality"),
        "aspect_ratio": job.get("ratio"),
        "duration": job.get("duration"),
        "reference_images": job.get("reference_images") or [],
        "reference_videos": job.get("reference_videos") or [],
    }


async def retry_job(job_id: str) -> dict:
    """Re-generate ONLY the failed model(s) of an existing job (keeping any
    successful side), then re-run the Core-5 auto-eval."""
    db = _get_firestore_client()
    snap = db.collection(EVAL_COLLECTION).document(job_id).get()
    if not snap.exists:
        return {"job_id": job_id, "status": "not_found"}
    job = snap.to_dict() or {}
    case = _case_from_job(job)
    results = job.get("results") or {}

    retried = []
    for key, res in list(results.items()):
        if isinstance(res, dict) and res.get("status") == "success":
            continue
        if "seedance" in key:
            newr = await generate_seedance(case)
        elif "omni" in key:
            newr = await generate_omni(case)
        else:
            continue
        db.collection(EVAL_COLLECTION).document(job_id).update({f"results.{key}": newr})
        retried.append({"model_key": key, "status": newr.get("status"), "error": newr.get("error", "")})

    # Reset eval status and re-score whatever now succeeds.
    db.collection(EVAL_COLLECTION).document(job_id).update({"auto_eval_status": "pending"})
    try:
        run_auto_eval(job_id)
    except Exception as e:  # pragma: no cover
        db.collection(EVAL_COLLECTION).document(job_id).update(
            {"auto_eval_status": "error", "auto_eval_error": str(e)}
        )
    return {"job_id": job_id, "retried": retried}


async def retry_failures(job_ids: List[str]) -> List[dict]:
    """Retry failed model(s) across the given jobs, one at a time (Omni QPM)."""
    sem = asyncio.Semaphore(1)

    async def _r(jid: str):
        async with sem:
            try:
                return await retry_job(jid)
            except Exception as e:  # pragma: no cover
                return {"job_id": jid, "error": str(e)}

    return await asyncio.gather(*[_r(j) for j in job_ids])


async def process_batch(pairs: List[tuple]) -> List[str]:
    """Process a list of (job_id, case) pairs that were already created.

    Concurrency capped at 1 case at a time (Omni EAP ~3 QPM; each case already
    fans out to 2 models). Bump the semaphore only if the Omni quota is raised.
    """
    sem = asyncio.Semaphore(1)

    async def _run(job_id: str, case: dict):
        async with sem:
            try:
                return await process_job(job_id, case)
            except Exception as e:  # pragma: no cover
                print(f"[sxs_pipeline] process_job failed {job_id}: {e}")
                return job_id

    return await asyncio.gather(*[_run(jid, c) for jid, c in pairs])


# --- Admin JSON-driven multi-model generation ------------------------------

# Per-customer modality overrides. Empty now that the source JSON carries a
# correct per-case modality (t2v/i2v/r2v); add entries only to force a customer.
CUSTOMER_MODALITY_OVERRIDE: Dict[str, str] = {}


def modality_to_type(modality: str) -> str:
    """Map a case modality string to a registry model `type` (t2v/i2v/r2v).

    Rules:
      - T2V                                   -> t2v
      - I2V (first frame) / FLF2V (first+last)-> i2v   (image-anchored)
      - V2V (video editing)                   -> r2v   (uses r2v-capable models + source video)
      - Ref2V / R2V / model-reference / else  -> r2v
    """
    m = str(modality or "").upper()
    if "T2V" in m:
        return "t2v"
    if "FLF2V" in m or "I2V" in m or "FIRST FRAME" in m or "FIRST-FRAME" in m:
        return "i2v"
    if "V2V" in m:
        return "r2v"
    # Ref2V / R2V / R2VSTORY / "provide model reference" / anything else
    return "r2v"


def case_model_type(case: dict) -> str:
    """Registry model type for a case, honoring per-customer overrides."""
    cust = str(case.get("customer", "")).strip().lower()
    if cust in CUSTOMER_MODALITY_OVERRIDE:
        return CUSTOMER_MODALITY_OVERRIDE[cust]
    return modality_to_type(case.get("modality") or case.get("mode") or "t2v")


def create_admin_job(case: dict, batch_id, model_list) -> str:
    """Create a Firestore job doc keyed by EACH model id in `model_list`.

    `model_list` is a list of dicts each with id/provider/model_id/type.
    Returns the job_id.
    """
    case_id = case.get("id", "case")
    job_id = f"adm_{_slug(case_id)}_{int(time.time()*1000)}"

    results = {m["id"]: {"status": "generating"} for m in model_list}
    doc = {
        "id": job_id,
        "source": "sxs_auto",
        "origin": "admin",
        "batch_id": batch_id,
        "customer": case.get("customer", ""),
        "prompt_id": case_id,
        "prompt": case.get("prompt", ""),
        "ratio": case.get("aspect_ratio", "16:9"),
        "modality": _modality(case),
        "duration": case.get("duration"),
        "reference_images": _ref_list(case, "reference_images"),
        "reference_videos": _ref_list(case, "reference_videos"),
        "timestamp": time.time(),
        "results": results,
        "auto_eval_status": "pending",
    }

    db = _get_firestore_client()
    db.collection(EVAL_COLLECTION).document(job_id).set(doc)
    return job_id


async def generate_for_model(model: dict, case: dict) -> dict:
    """Generate one case on one registry model. Routes by provider.

    Reuses the proven local Omni path (handles image+video). Seedance and other
    fal models go through `generate_with_fal` so the EXACT endpoint (fast vs
    regular, t2v/i2v/r2v) is used and reference_videos are wired through.
    """
    provider = model.get("provider")
    mode = model.get("type", "t2v")

    ref_images = _ref_list(case, "reference_images")
    ref_videos = _ref_list(case, "reference_videos")
    image_url = ref_images[0] if (mode == "i2v" and ref_images) else None
    # FLF2V (first & last frame locked) arrives as an i2v case with 2 ref images.
    end_image_url = ref_images[1] if (mode == "i2v" and len(ref_images) >= 2) else None
    prompt = case.get("prompt", "") or ""
    ratio = case.get("aspect_ratio", "16:9")

    if provider == "omni":
        # Local omni path base64-encodes reference images + videos correctly.
        return await generate_omni(case)

    if provider == "fal":
        from providers.fal_provider import generate_with_fal
        return await generate_with_fal(
            model["model_id"], prompt, ratio, image_url, end_image_url,
            ref_images if mode == "r2v" else None,
            mode=mode,
            reference_videos=ref_videos if mode == "r2v" else None,
        )

    if provider == "vertex":
        from providers.vertex_provider import generate_with_veo
        return await generate_with_veo(
            prompt, ratio, image_url, model["model_id"],
            ref_images if mode == "r2v" else None, mode=mode,
        )

    return _standard_result(
        model.get("id", "unknown"), status="error",
        error=f"Unknown provider: {provider}",
    )


async def process_admin_job(job_id: str, case: dict, model_list: list) -> str:
    """Generate concurrently on every model in `model_list`, patch results, then
    run the Core-5 auto-eval. Returns the job_id."""
    gen_results = await asyncio.gather(
        *[generate_for_model(m, case) for m in model_list],
        return_exceptions=True,
    )

    db = _get_firestore_client()
    update_payload: Dict[str, Any] = {}
    for model, res in zip(model_list, gen_results):
        if isinstance(res, Exception):
            res = {"status": "error", "error": str(res)}
        update_payload[f"results.{model['id']}"] = res
    if update_payload:
        db.collection(EVAL_COLLECTION).document(job_id).update(update_payload)

    try:
        run_auto_eval(job_id)
    except Exception as e:  # pragma: no cover
        print(f"[sxs_pipeline] admin auto-eval failed for {job_id}: {e}")
        try:
            db.collection(EVAL_COLLECTION).document(job_id).update(
                {"auto_eval_status": "error", "auto_eval_error": str(e)}
            )
        except Exception:
            pass

    return job_id


async def process_admin_batch(pairs: list) -> list:
    """Process (job_id, case, model_list) triples one case at a time (Omni QPM)."""
    sem = asyncio.Semaphore(1)

    async def _run(job_id: str, case: dict, model_list: list):
        async with sem:
            try:
                return await process_admin_job(job_id, case, model_list)
            except Exception as e:  # pragma: no cover
                print(f"[sxs_pipeline] process_admin_job failed {job_id}: {e}")
                return job_id

    return await asyncio.gather(*[_run(jid, c, ml) for jid, c, ml in pairs])


def run_auto_eval(job_id: str) -> None:
    """Run Core-5 evaluation on each successfully-generated video.

    Downloads each video plus the reference images/videos to temp files, then
    calls run_core5_evaluation for each model concurrently. Reference videos
    double as `source_videos`. Results are stored under auto_evals[model_key].
    """
    from video_evaluator_sdk import run_core5_evaluation, run_director_pairwise  # lazy import

    db = _get_firestore_client()
    doc_ref = db.collection(EVAL_COLLECTION).document(job_id)
    snap = doc_ref.get()
    if not snap.exists:
        raise RuntimeError(f"Job {job_id} not found")
    job = snap.to_dict() or {}

    doc_ref.update({"auto_eval_status": "running"})

    prompt = job.get("prompt", "") or ""
    results = job.get("results", {}) or {}
    temp_paths: List[str] = []

    def _to_temp(url: str, suffix: str) -> str:
        data = download_blob_to_bytes(url)
        fd, path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        temp_paths.append(path)
        return path

    try:
        # Shared reference assets (same for every model under one case).
        ref_image_paths: List[str] = []
        for url in job.get("reference_images", []) or []:
            try:
                ref_image_paths.append(_to_temp(url, ".png"))
            except Exception as e:
                print(f"[sxs_pipeline] ref image download failed {url}: {e}")

        source_video_paths: List[str] = []
        for url in job.get("reference_videos", []) or []:
            try:
                source_video_paths.append(_to_temp(url, ".mp4"))
            except Exception as e:
                print(f"[sxs_pipeline] ref video download failed {url}: {e}")

        # Build the set of model evaluations to run.
        tasks: List[tuple] = []  # (model_key, video_temp_path)
        for model_key, res in results.items():
            if not isinstance(res, dict) or res.get("status") != "success":
                continue
            video_url = res.get("url") or (res.get("result") or {}).get("url")
            if not video_url:
                continue
            try:
                video_path = _to_temp(video_url, ".mp4")
            except Exception as e:
                print(f"[sxs_pipeline] video download failed {model_key}: {e}")
                continue
            tasks.append((model_key, video_path))

        # Core-5 (5-point) auto-eval is DISABLED for video — the Creative
        # Director pairwise critique below is the sole AI eval for video.
        update_payload: Dict[str, Any] = {"auto_eval_status": "done"}

        # Pairwise "Creative Director" verdict — only when BOTH models produced
        # video. Video A = Seedance, Video B = Omni (fixed mapping for the AI judge).
        path_by_key = {mk: vp for mk, vp in tasks}
        a_path = path_by_key.get(SEEDANCE_KEY)
        b_path = next((vp for mk, vp in tasks if "omni" in mk), None)
        if a_path and b_path:
            try:
                director = run_director_pairwise(a_path, b_path, prompt, ref_image_paths or None)
                if director:
                    omni_key = next((mk for mk, _ in tasks if "omni" in mk), "omni")
                    verdict = (director.get("verdict") or "").strip().upper()
                    director["winner_model"] = SEEDANCE_KEY if verdict == "A" else (omni_key if verdict == "B" else None)
                    director["video_a"] = SEEDANCE_KEY
                    director["video_b"] = omni_key
                    director["evaluated_at"] = time.time()
                    director["model"] = AUTO_EVAL_MODEL_NAME
                    update_payload["director_eval"] = director
            except Exception as e:
                print(f"[sxs_pipeline] director eval failed: {e}")

        doc_ref.update(update_payload)
    except Exception as e:
        doc_ref.update({"auto_eval_status": "error", "auto_eval_error": str(e)})
        raise
    finally:
        for p in temp_paths:
            try:
                os.remove(p)
            except OSError:
                pass


def run_director_for_job(job_id: str) -> Optional[str]:
    """Run ONLY the pairwise director critique on an existing job's two videos
    and store it under `director_eval`. Returns the winner model key or None."""
    from video_evaluator_sdk import run_director_pairwise  # lazy import

    db = _get_firestore_client()
    doc_ref = db.collection(EVAL_COLLECTION).document(job_id)
    snap = doc_ref.get()
    if not snap.exists:
        return None
    job = snap.to_dict() or {}
    results = job.get("results", {}) or {}

    def _success_url(key_pred):
        for k, r in results.items():
            if key_pred(k) and isinstance(r, dict) and r.get("status") == "success":
                return k, (r.get("url") or (r.get("result") or {}).get("url"))
        return None, None

    a_key, a_url = _success_url(lambda k: "seedance" in k)
    b_key, b_url = _success_url(lambda k: "omni" in k)
    if not (a_url and b_url):
        return None

    temp_paths: List[str] = []

    def _to_temp(url: str, suffix: str) -> str:
        data = download_blob_to_bytes(url)
        fd, path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        temp_paths.append(path)
        return path

    try:
        a_path = _to_temp(a_url, ".mp4")
        b_path = _to_temp(b_url, ".mp4")
        ref_paths = []
        for u in job.get("reference_images", []) or []:
            try:
                ref_paths.append(_to_temp(u, ".png"))
            except Exception:
                pass
        director = run_director_pairwise(a_path, b_path, job.get("prompt", "") or "", ref_paths or None)
        if not director:
            return None
        verdict = (director.get("verdict") or "").strip().upper()
        director["winner_model"] = SEEDANCE_KEY if verdict == "A" else (b_key if verdict == "B" else None)
        director["video_a"] = SEEDANCE_KEY
        director["video_b"] = b_key
        director["evaluated_at"] = time.time()
        director["model"] = AUTO_EVAL_MODEL_NAME
        doc_ref.update({"director_eval": director})
        return director["winner_model"]
    finally:
        for p in temp_paths:
            try:
                os.remove(p)
            except OSError:
                pass


def director_backfill(job_ids: List[str]) -> None:
    """Run the director critique sequentially over the given job ids."""
    for jid in job_ids:
        try:
            run_director_for_job(jid)
        except Exception as e:  # pragma: no cover
            print(f"[sxs_pipeline] director backfill failed {jid}: {e}")


async def run_batch(cases: list) -> List[str]:
    """Run run_case over all cases.

    NOTE: Omni EAP is rate-limited (~3 QPM), so we deliberately cap concurrency
    to 1 case at a time (each case already fans out to 2 models). Bump the
    semaphore to 2 only if the Omni quota is raised.
    """
    sem = asyncio.Semaphore(1)
    job_ids: List[str] = []

    async def _run(case: dict):
        async with sem:
            try:
                return await run_case(case)
            except Exception as e:  # pragma: no cover
                print(f"[sxs_pipeline] case failed: {e}")
                return None

    for jid in await asyncio.gather(*[_run(c) for c in cases]):
        if jid:
            job_ids.append(jid)
    return job_ids
