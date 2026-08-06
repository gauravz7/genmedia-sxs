"""Pre-multi-modality endpoints, kept for compatibility.

/api/generate, /api/generate-image, /api/upload and /api/evaluation/* predate
the three-modality split and are no longer called by the frontend — the live
paths are /api/{sxs,image,tts}/*. Don't extend these."""

import os
import random
import time
from collections import defaultdict
from typing import Dict, Optional
from urllib.parse import unquote

import requests
import fal_client
from fastapi import (APIRouter, BackgroundTasks, Depends, File, HTTPException,
                     Query, UploadFile)
from pydantic import BaseModel

from auth import require_admin
from generation import PromptRequest, _run_generation_background
from tagging import _auto_tag_job
from config import (VALID_RATIOS,
                    normalize_gcs_url)
from registry import registry
from store import Job, Vote, jobs_manager, votes_manager
from util.gcs_utils import get_signed_url, get_upload_client, https_to_gs, upload_from_url

router = APIRouter()


@router.post("/api/generate-image", dependencies=[Depends(require_admin)])
async def generate_image_api(request: dict):
    prompt = request.get("prompt")
    ratio = request.get("ratio", "16:9")
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt is required")

    fal_size = "landscape_16_9" if ratio == "16:9" else "portrait_9_16"
    try:
        result = await fal_client.run_async("fal-ai/flux/schnell", arguments={"prompt": prompt, "image_size": fal_size})
        image_url = result["images"][0]["url"]
        filename = f"gen_img_{int(time.time())}.png"
        gcs_url = upload_from_url(image_url, filename)
        signed_url = get_signed_url(gcs_url) if gcs_url else image_url
        return {"status": "success", "url": signed_url, "raw_url": gcs_url or image_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/upload", dependencies=[Depends(require_admin)])
async def upload_file_api(file: UploadFile = File(...)):
    try:
        safe_filename = "".join(c for c in file.filename if c.isalnum() or c in "._-").replace(" ", "_")
        if not safe_filename:
            safe_filename = "file"
        filename = f"uploads/{int(time.time())}_{safe_filename}"
        content = await file.read()
        from util.gcs_utils import upload_from_bytes
        gcs_url = upload_from_bytes(content, filename, content_type=file.content_type)
        signed_url = get_signed_url(gcs_url)
        return {"status": "success", "url": signed_url, "raw_url": gcs_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/generate", dependencies=[Depends(require_admin)])
async def generate_videos(request: PromptRequest, background_tasks: BackgroundTasks):
    initiation_time = time.time()

    # Validate ratio
    if request.ratio not in VALID_RATIOS:
        request.ratio = "16:9"

    # Infer mode
    mode = request.mode
    if not mode:
        if request.reference_images and len(request.reference_images) > 0:
            mode = "r2v"
        elif request.start_image_url or request.reference_image_url:
            mode = "i2v"
        else:
            mode = "t2v"

    # Select models — when model_ids are explicitly provided (e.g. batch),
    # use them directly without filtering by inferred mode so that the caller
    # controls exactly which models run.
    if request.model_ids:
        # Video types only — the registry also holds image (t2i) and TTS models.
        all_requested = [
            registry.models[mid] for mid in request.model_ids
            if mid in registry.models and registry.models[mid].type in ("t2v", "i2v", "r2v")
        ]
        # If the caller explicitly chose models, trust them (don't filter by mode).
        # Fall back to mode-filtering only when none of the requested models match
        # any type, which likely means the IDs were wrong.
        target_models = all_requested if all_requested else []
    else:
        target_models = [m for m in registry.get_active_models() if m.type == mode]

    if not target_models:
        print(f"WARNING: No active models for mode {mode}")

    # Normalize URLs
    request.start_image_url = normalize_gcs_url(request.start_image_url)
    request.end_image_url = normalize_gcs_url(request.end_image_url)
    request.reference_image_url = normalize_gcs_url(request.reference_image_url)
    if request.reference_images:
        request.reference_images = [normalize_gcs_url(u) for u in request.reference_images]

    prompt_id = request.prompt_id or f"job_{int(time.time() * 1000)}"

    # --- Reuse existing job if same prompt_id already exists ---
    # This allows batch rows with the same promptId to accumulate results
    # into a single job rather than creating duplicates.
    existing_job = None
    for j in jobs_manager.jobs.values():
        if j.prompt_id == prompt_id:
            existing_job = j
            break

    if existing_job:
        # Only generate models that don't already have successful results
        models_to_generate = []
        for m in target_models:
            if m.id not in existing_job.results or existing_job.results[m.id].get("status") in ("error", "generating", None):
                existing_job.results[m.id] = {"status": "generating"}
                models_to_generate.append(m)
            else:
                print(f"Skipping {m.id} — already has status '{existing_job.results[m.id].get('status')}'")

        if not models_to_generate:
            print(f"All requested models already successful for {prompt_id}, skipping generation.")
            return {"job_id": existing_job.id, "prompt": request.text, "status": "already_complete", "initiation_time": initiation_time}

        jobs_manager.save_job(existing_job)
        job_id = existing_job.id

        background_tasks.add_task(_run_generation_background, job_id, models_to_generate, request, initiation_time)

        # Auto-tag if the existing job has no categories
        if not existing_job.categories:
            background_tasks.add_task(
                _auto_tag_job, job_id, request.text,
                request.start_image_url, request.end_image_url, request.reference_images,
            )

        return {"job_id": job_id, "prompt": request.text, "status": "queued", "initiation_time": initiation_time}

    # --- Create new job ---
    job_id = f"job_{int(time.time() * 1000)}"

    job = Job(
        id=job_id,
        prompt=request.text,
        prompt_id=prompt_id,
        categories=request.categories,
        ratio=request.ratio,
        timestamp=time.time(),
        initiation_time=initiation_time,
        start_image_url=request.start_image_url,
        end_image_url=request.end_image_url,
        reference_image_url=request.reference_image_url,
        reference_images=request.reference_images,
        results={m.id: {"status": "generating"} for m in target_models},
    )
    jobs_manager.save_job(job)

    background_tasks.add_task(_run_generation_background, job_id, target_models, request, initiation_time)

    # Auto-generate tags if none provided
    if not request.categories:
        background_tasks.add_task(
            _auto_tag_job, job_id, request.text,
            request.start_image_url, request.end_image_url, request.reference_images,
        )

    return {"job_id": job_id, "prompt": request.text, "status": "queued", "initiation_time": initiation_time}



def _extract_url(res):
    url = None
    if "url" in res:
        url = res["url"]
    elif "result" in res and isinstance(res["result"], dict):
        if "url" in res["result"]:
            url = res["result"]["url"]
        elif "video" in res["result"] and isinstance(res["result"]["video"], dict):
            url = res["result"]["video"].get("url")
        elif "video_url" in res["result"]:
            url = res["result"]["video_url"]

    if url and (url.startswith("gs://") or "storage.googleapis.com" in url):
        if "X-Goog-Signature" not in url:
            return get_signed_url(url)
    return url


def _is_url_accessible(url):
    if not url:
        return False
    try:
        check_url = url
        if "/api/media?url=" in check_url:
            check_url = unquote(check_url.split("/api/media?url=")[-1])
        check_url = https_to_gs(check_url)
        if check_url.startswith("gs://"):
            client = get_upload_client()
            bucket_name = check_url.split("gs://")[1].split("/")[0]
            blob_name = check_url.split(f"gs://{bucket_name}/")[1]
            return client.bucket(bucket_name).blob(blob_name).exists()
        resp = requests.get(url, timeout=3, stream=True)
        return resp.status_code == 200
    except Exception:
        return False


@router.get("/api/evaluation/pair")
async def get_random_eval_pair(
    prompt_id: Optional[str] = None,
    tag: Optional[str] = None,
    search: Optional[str] = None,
    veo_anchored: bool = False,
    source: Optional[str] = None,
):
    """
    Returns a random pair of successful variants for SxS evaluation.
    Supports filtering by prompt_id, tag (category), or free-text search on prompt.
    When veo_anchored=true, one side is always a Veo model.
    When source is given (e.g. "sxs_auto"), only jobs from that source are paired.
    """
    groups = defaultdict(dict)

    for job in jobs_manager.jobs.values():
        # --- Filter by source (e.g. SxS auto pipeline) ---
        if source and getattr(job, "source", None) != source:
            continue
        # --- Filter by tag ---
        if tag and tag.lower() not in [c.lower() for c in job.categories]:
            continue
        # --- Filter by prompt text search ---
        if search and search.lower() not in job.prompt.lower():
            continue

        group_key = getattr(job, "prompt_id", None) or job.prompt
        for mid, res in job.results.items():
            if res.get("status") == "success":
                url = _extract_url(res)
                if url:
                    groups[group_key][mid] = (job, url)

        # Include regenerations (previous versions) as separate candidates
        for mid, versions in job.generation_history.items():
            for vi, ver in enumerate(versions, 1):
                if ver.get("status") == "success":
                    url = _extract_url(ver)
                    if url:
                        version_label = f"{mid} (v{vi})"
                        groups[group_key][version_label] = (job, url)

    if veo_anchored:
        # Only keep groups that have at least 1 Veo + 1 non-Veo model
        valid_groups = {}
        for k, v in groups.items():
            veo = {m: d for m, d in v.items() if "veo" in m.lower()}
            non_veo = {m: d for m, d in v.items() if "veo" not in m.lower()}
            if veo and non_veo:
                valid_groups[k] = v
    else:
        valid_groups = {k: v for k, v in groups.items() if len(v) >= 2}

    if prompt_id:
        filtered = {k: v for k, v in valid_groups.items() if str(k) == str(prompt_id)}
        if filtered:
            valid_groups = filtered

    if not valid_groups:
        return {"status": "error", "message": "No prompt found with at least two successful models matching your filters."}

    group_keys = list(valid_groups.keys())
    random.shuffle(group_keys)

    for g_key in group_keys[:20]:
        candidates = valid_groups[g_key]
        accessible = [(mid, job, url) for mid, (job, url) in candidates.items() if _is_url_accessible(url)]

        if veo_anchored:
            veo_list = [x for x in accessible if "veo" in x[0].lower()]
            non_veo_list = [x for x in accessible if "veo" not in x[0].lower()]
            if not veo_list or not non_veo_list:
                continue
            veo_pick = random.choice(veo_list)
            non_veo_pick = random.choice(non_veo_list)
            # Randomly assign to side A or B so evaluator can't guess
            pair = [veo_pick, non_veo_pick]
            random.shuffle(pair)
        else:
            if len(accessible) < 2:
                continue
            pair = random.sample(accessible, 2)

        side_a_model, job_a, url_a = pair[0]
        side_b_model, job_b, url_b = pair[1]

        return {
            "job_id": getattr(job_a, "prompt_id", None) or job_a.id,
            "prompt": job_a.prompt,
            "categories": job_a.categories,
            "ratio": getattr(job_a, "ratio", "16:9"),
            "start_image_url": get_signed_url(job_a.start_image_url) if job_a.start_image_url else None,
            "end_image_url": get_signed_url(job_a.end_image_url) if job_a.end_image_url else None,
            "reference_image_url": get_signed_url(job_a.reference_image_url) if job_a.reference_image_url else None,
            "reference_images": [get_signed_url(u) for u in job_a.reference_images] if job_a.reference_images else None,
            "variant_a": {"model_id": side_a_model, "url": url_a},
            "variant_b": {"model_id": side_b_model, "url": url_b},
        }

    return {"status": "error", "message": "Could not find a fully accessible video pair after scanning history."}


class VoteRequest(BaseModel):
    job_id: str
    winner_side: str
    winner_model: str
    loser_model: str
    scores: Dict[str, int]
    justification: str
    ldap: str = "anonymous"


@router.post("/api/evaluation/vote")
async def cast_vote(req: VoteRequest):
    vote_id = f"vote_{int(time.time())}"
    vote = Vote(
        id=vote_id, job_id=req.job_id, winner_side=req.winner_side,
        winner_model=req.winner_model, loser_model=req.loser_model,
        scores=req.scores, justification=req.justification,
        timestamp=time.time(), ldap=req.ldap,
    )
    votes_manager.add_vote(vote)
    return {"status": "success", "vote_id": vote_id}


@router.post("/api/admin/votes/prune", dependencies=[Depends(require_admin)])
async def prune_votes(keep: int = Query(20, ge=1)):
    """Keep only the most recent `keep` votes, delete the rest."""
    from google.cloud import firestore as _fs
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
    docs = list(db.collection("votes").order_by("timestamp", direction=_fs.Query.DESCENDING).stream())
    total = len(docs)
    if total <= keep:
        return {"status": "nothing_to_delete", "total": total, "keep": keep}
    to_delete = docs[keep:]
    batch = db.batch()
    for i, doc in enumerate(to_delete):
        batch.delete(db.collection("votes").document(doc.id))
        if (i + 1) % 500 == 0:
            batch.commit()
            batch = db.batch()
    batch.commit()
    return {"status": "success", "total_before": total, "kept": keep, "deleted": len(to_delete)}
