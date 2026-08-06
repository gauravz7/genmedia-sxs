"""Admin surface: login, prompt CRUD, tags, Sheets batches, and the
legacy jobs view (/api/admin/*)."""

import os
import time

from fastapi import (APIRouter, BackgroundTasks, Depends, HTTPException)
from pydantic import BaseModel

from auth import require_admin
from auth import ADMIN_PASS, ADMIN_USER, _admin_token
from generation import PromptRequest, _run_generation_background
from providers.vertex_provider import generate_tags_with_gemini
from tagging import _auto_tag_prompt
from config import (GCS_BUCKET_NAME, normalize_gcs_url)
from registry import registry
from store import Prompt, jobs_manager, prompts_manager
from util.gcs_utils import get_signed_url

router = APIRouter()


@router.post("/api/admin/login")
async def admin_login(creds: dict):
    if not ADMIN_PASS:
        raise HTTPException(status_code=500, detail="ADMIN_PASS not configured")
    if creds.get("username") == ADMIN_USER and creds.get("password") == ADMIN_PASS:
        return {"status": "success", "token": _admin_token()}
    raise HTTPException(status_code=401, detail="Invalid credentials")


@router.get("/api/admin/prompts")
async def get_admin_prompts():
    return prompts_manager.get_all()


@router.post("/api/admin/prompts", dependencies=[Depends(require_admin)])
async def add_admin_prompt(req: dict, background_tasks: BackgroundTasks):
    prompt_id = req.get("id") or f"prompt_{int(time.time())}"
    categories = req.get("categories", [req["category"]] if req.get("category") else [])
    prompt = Prompt(
        id=prompt_id,
        text=req["text"],
        categories=categories,
        start_image_url=normalize_gcs_url(req.get("start_image_url")),
        end_image_url=normalize_gcs_url(req.get("end_image_url")),
        reference_image_url=normalize_gcs_url(req.get("reference_image_url")),
        reference_images=[normalize_gcs_url(u) for u in req.get("reference_images", [])] if req.get("reference_images") else None,
        models=req.get("models", ["Veo", "Kling", "Seedance"]),
        status=req.get("status", "pending"),
        timestamp=time.time(),
    )
    prompts_manager.save_prompt(prompt)

    # Auto-generate tags if none provided
    if not categories:
        background_tasks.add_task(
            _auto_tag_prompt, prompt_id, req["text"],
            req.get("start_image_url"), req.get("end_image_url"), req.get("reference_images"),
        )

    return {"status": "success", "prompt": prompt}


@router.delete("/api/admin/prompts/{prompt_id}", dependencies=[Depends(require_admin)])
async def delete_admin_prompt(prompt_id: str):
    if prompts_manager.delete_prompt(prompt_id):
        return {"status": "success"}
    return {"status": "error", "message": "Prompt not found"}


@router.post("/api/admin/generate-tags", dependencies=[Depends(require_admin)])
async def generate_tags_endpoint(request: dict):
    tags = await generate_tags_with_gemini(
        request.get("text", ""),
        request.get("start_image_url"),
        request.get("end_image_url"),
        request.get("reference_images"),
    )
    return {"status": "success", "tags": tags}


@router.get("/api/tags")
async def get_all_tags():
    """Returns all unique tags across jobs and prompts for search/filter UI."""
    tags = set()
    for job in jobs_manager.jobs.values():
        for t in job.categories:
            tags.add(t)
    for prompt in prompts_manager.prompts.values():
        for t in prompt.categories:
            tags.add(t)
    return {"status": "success", "tags": sorted(tags)}


@router.post("/api/admin/backfill-tags", dependencies=[Depends(require_admin)])
async def backfill_tags():
    """Auto-generate tags for all jobs and prompts that have no categories."""
    tagged_jobs = 0
    tagged_prompts = 0

    for job in jobs_manager.jobs.values():
        if not job.categories:
            try:
                tags = await generate_tags_with_gemini(
                    job.prompt, job.start_image_url, job.end_image_url, job.reference_images,
                )
                job.categories = tags
                jobs_manager.save_job(job)
                tagged_jobs += 1
                print(f"Backfill tagged job {job.id}: {tags}")
            except Exception as e:
                print(f"Backfill error for job {job.id}: {e}")

    for prompt in prompts_manager.prompts.values():
        if not prompt.categories:
            try:
                tags = await generate_tags_with_gemini(
                    prompt.text, prompt.start_image_url, prompt.end_image_url,
                    prompt.reference_images,
                )
                prompt.categories = tags
                prompts_manager.save_prompt(prompt)
                tagged_prompts += 1
                print(f"Backfill tagged prompt {prompt.id}: {tags}")
            except Exception as e:
                print(f"Backfill error for prompt {prompt.id}: {e}")

    jobs_manager.invalidate_cache()
    return {"status": "success", "tagged_jobs": tagged_jobs, "tagged_prompts": tagged_prompts}


from util.sheets_utils import read_sheet, update_sheet_row


class SheetLoadRequest(BaseModel):
    url: str


class SheetUpdateRequest(BaseModel):
    url: str
    row: int
    success: bool
    error: str = ""


@router.post("/api/admin/batch/sheet/load", dependencies=[Depends(require_admin)])
async def load_batch_sheet(req: SheetLoadRequest):
    try:
        data = read_sheet(req.url)
        return {"status": "success", "rows": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/admin/batch/sheet/update", dependencies=[Depends(require_admin)])
async def update_batch_sheet(req: SheetUpdateRequest):
    try:
        update_sheet_row(req.url, req.row, req.success, req.error)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/admin/jobs")
async def get_admin_jobs():
    from google.cloud import firestore as _fs
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
    docs = db.collection("eval_jobs").order_by("timestamp", direction=_fs.Query.DESCENDING).stream()
    results_list = []
    for doc in docs:
        d = doc.to_dict()
        d["id"] = doc.id
        # Sign input images
        for key in ("start_image_url", "end_image_url", "reference_image_url"):
            if d.get(key):
                d[key] = get_signed_url(normalize_gcs_url(d[key]))
        if d.get("reference_images"):
            d["reference_images"] = [get_signed_url(normalize_gcs_url(u)) for u in d["reference_images"]]
        # Sign result URLs
        for model_id, res in d.get("results", {}).items():
            if "url" in res and res["url"]:
                if res["url"].startswith("gs://") or f"storage.googleapis.com/{GCS_BUCKET_NAME}" in res["url"]:
                    res["url"] = get_signed_url(normalize_gcs_url(res["url"]))
            if "result" in res and isinstance(res["result"], dict) and "url" in res["result"] and res["result"]["url"]:
                if res["result"]["url"].startswith("gs://") or f"storage.googleapis.com/{GCS_BUCKET_NAME}" in res["result"]["url"]:
                    res["result"]["url"] = get_signed_url(normalize_gcs_url(res["result"]["url"]))
        # Sign generation history URLs
        for model_id, versions in d.get("generation_history", {}).items():
            for ver in versions:
                if "url" in ver and ver["url"]:
                    if ver["url"].startswith("gs://") or f"storage.googleapis.com/{GCS_BUCKET_NAME}" in ver["url"]:
                        ver["url"] = get_signed_url(normalize_gcs_url(ver["url"]))
                if "result" in ver and isinstance(ver["result"], dict) and "url" in ver["result"] and ver["result"]["url"]:
                    if ver["result"]["url"].startswith("gs://") or f"storage.googleapis.com/{GCS_BUCKET_NAME}" in ver["result"]["url"]:
                        ver["result"]["url"] = get_signed_url(normalize_gcs_url(ver["result"]["url"]))
        results_list.append(d)
    return results_list


@router.delete("/api/admin/jobs/{job_id}", dependencies=[Depends(require_admin)])
async def delete_job(job_id: str):
    """Delete a job from Firestore."""
    from google.cloud import firestore as _fs
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
    doc_ref = db.collection("eval_jobs").document(job_id)
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Job not found")
    doc_ref.delete()
    jobs_manager.invalidate_cache()
    return {"status": "deleted", "job_id": job_id}


@router.post("/api/admin/jobs/{job_id}/retry", dependencies=[Depends(require_admin)])
async def retry_failed_models(job_id: str, background_tasks: BackgroundTasks, include_stuck: bool = False):
    """Retry failed/error models in a job. With include_stuck=true, also retries models stuck in 'generating'."""
    from google.cloud import firestore as _fs
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
    doc_ref = db.collection("eval_jobs").document(job_id)
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Job not found")

    data = doc.to_dict()
    results = data.get("results", {})

    # Find models to retry: errored + optionally stuck "generating" models
    retry_statuses = {"error"}
    if include_stuck:
        retry_statuses.add("generating")
    failed_model_ids = [mid for mid, r in results.items() if r.get("status") in retry_statuses]
    if not failed_model_ids:
        return {"status": "no_failures", "job_id": job_id, "message": "No failed or stuck models to retry"}

    # Look up registered models
    retry_models = [registry.models[mid] for mid in failed_model_ids if mid in registry.models]
    skipped = [mid for mid in failed_model_ids if mid not in registry.models]
    if not retry_models:
        raise HTTPException(status_code=400, detail=f"Models not in registry (re-add them in Models tab): {failed_model_ids}")
    if skipped:
        print(f"Retry skipping unregistered models: {skipped}")

    # Only retry models that are in the registry
    retrying_ids = [m.id for m in retry_models]

    # Mark them as generating again
    for mid in retrying_ids:
        results[mid] = {"status": "generating"}
    doc_ref.update({"results": results})
    jobs_manager.invalidate_cache()

    # Reconstruct PromptRequest from job data
    request = PromptRequest(
        text=data.get("prompt", ""),
        categories=data.get("categories", []),
        ratio=data.get("ratio", "16:9"),
        prompt_id=data.get("prompt_id"),
        start_image_url=data.get("start_image_url"),
        end_image_url=data.get("end_image_url"),
        reference_image_url=data.get("reference_image_url"),
        reference_images=data.get("reference_images"),
        model_ids=retrying_ids,
    )

    background_tasks.add_task(_run_generation_background, job_id, retry_models, request, time.time())

    return {"status": "retrying", "job_id": job_id, "retrying_models": retrying_ids, "skipped_models": skipped}


@router.get("/api/admin/jobs/{job_id}/status")
async def get_job_status(job_id: str):
    """Return per-model generation status for a single job.
    Always reads fresh from Firestore to avoid stale cache during polling."""
    from google.cloud import firestore as _fs
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
    doc = db.collection("eval_jobs").document(job_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Job not found")

    data = doc.to_dict()
    results = data.get("results", {})

    all_done = all(
        r.get("status") not in (None, "generating", "queued")
        for r in results.values()
    ) if results else False

    # Only count as succeeded if status is "success" AND a video URL exists
    succeeded = sum(
        1 for r in results.values()
        if r.get("status") == "success" and (r.get("url") or (isinstance(r.get("result"), dict) and r["result"].get("url")))
    )
    failed = sum(1 for r in results.values() if r.get("status") == "error")
    errors = [
        {"model": k, "error": r.get("error", "")}
        for k, r in results.items() if r.get("status") == "error"
    ]

    return {
        "job_id": job_id,
        "all_done": all_done,
        "total_models": len(results),
        "succeeded": succeeded,
        "failed": failed,
        "errors": errors,
    }
