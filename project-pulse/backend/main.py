import os
import json
import asyncio
import time
import random
import requests
import fal_client
import logging
from collections import defaultdict, Counter
from typing import List, Dict, Optional
from urllib.parse import quote, unquote

from fastapi import FastAPI, HTTPException, UploadFile, File, Header, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

from providers.fal_provider import generate_with_fal
from providers.vertex_provider import generate_with_veo, generate_tags_with_gemini
from util.gcs_utils import upload_from_url, get_signed_url, normalize_gcs_url as _normalize_gcs_url, https_to_gs, get_upload_client

load_dotenv()

app = FastAPI(title="Project Pulse API")

# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    body = exc.body
    if not isinstance(body, (dict, list, str, int, float, bool, type(None))):
        body = "<non-serializable body>"
    print(f"Validation Error: {exc.errors()}")
    return JSONResponse(status_code=422, content={"detail": exc.errors(), "body": body})

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# GCP config
# ---------------------------------------------------------------------------
os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "vital-octagon-19612")
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "project-pulse")

VALID_RATIOS = ["16:9", "9:16"]

print(f"Starting with Project ID: {GCP_PROJECT_ID}")


def normalize_gcs_url(url: str) -> str:
    """Strip signed-URL query params and proxy wrappers from GCS URLs."""
    if not url:
        return url
    if "/api/media?url=" in url:
        encoded = url.split("/api/media?url=")[-1]
        return unquote(encoded)
    if "X-Goog-Signature" in url or "?X-Goog-Algorithm" in url:
        return url.split("?")[0]
    return url


# ===================================================================
# Models / Managers
# ===================================================================

class RegisteredModel(BaseModel):
    id: str
    name: str
    provider: str       # 'fal' or 'vertex'
    model_id: str
    type: str = "t2v"   # 't2v', 'i2v', 'r2v'
    is_active: bool = True


class RegistryManager:
    def __init__(self, file_path="models.json"):
        self.file_path = file_path
        self.models: Dict[str, RegisteredModel] = self._load()

    def _load(self):
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r") as f:
                    data = json.load(f)
                    return {k: RegisteredModel(**v) for k, v in data.items()}
            except Exception as e:
                print(f"Error loading models.json: {e}")
        return {"veo": RegisteredModel(id="veo", name="Veo 2.0", provider="vertex", model_id="veo-2.0-generate-001", type="i2v")}

    def save(self):
        with open(self.file_path, "w") as f:
            json.dump({k: v.dict() for k, v in self.models.items()}, f, indent=2)

    def add_model(self, model: RegisteredModel):
        self.models[model.id] = model
        self.save()

    def toggle_model(self, model_id: str):
        if model_id in self.models:
            self.models[model_id].is_active = not self.models[model_id].is_active
            self.save()
            return True
        return False

    def get_active_models(self) -> List[RegisteredModel]:
        return [m for m in self.models.values() if m.is_active]


class Job(BaseModel):
    id: str
    prompt: str
    categories: List[str] = []
    ratio: str = "16:9"
    timestamp: float
    initiation_time: Optional[float] = None
    prompt_id: Optional[str] = None
    start_image_url: Optional[str] = None
    end_image_url: Optional[str] = None
    reference_image_url: Optional[str] = None
    reference_images: Optional[List[str]] = None
    results: Dict[str, dict]

    def __init__(self, **data):
        # Migrate legacy single-category field
        if "category" in data:
            cat = data.pop("category")
            if cat and not data.get("categories"):
                data["categories"] = [cat]
        super().__init__(**data)


class JobsManager:
    def __init__(self):
        from google.cloud import firestore
        self.db = firestore.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
        self._cached_jobs = None
        self._last_fetch_time = 0
        self.CACHE_TTL = 300

    @property
    def jobs(self):
        if self._cached_jobs is None or time.time() - self._last_fetch_time > self.CACHE_TTL:
            docs = self.db.collection("eval_jobs").stream()
            self._cached_jobs = {doc.id: Job(**doc.to_dict()) for doc in docs}
            self._last_fetch_time = time.time()
        return self._cached_jobs

    def invalidate_cache(self):
        self._cached_jobs = None

    def save_job(self, job: Job):
        self.db.collection("eval_jobs").document(job.id).set(job.dict())
        self.invalidate_cache()

    def get_all(self):
        from google.cloud import firestore
        docs = self.db.collection("eval_jobs").order_by("timestamp", direction=firestore.Query.DESCENDING).stream()
        return [Job(**doc.to_dict()) for doc in docs]


class Vote(BaseModel):
    id: str
    job_id: str
    winner_side: str
    winner_model: str
    loser_model: str
    scores: Dict[str, int]
    justification: str
    timestamp: float
    ldap: str = "anonymous"


class VotesManager:
    def __init__(self):
        from google.cloud import firestore
        self.db = firestore.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))

    @property
    def votes(self):
        return [Vote(**doc.to_dict()) for doc in self.db.collection("votes").stream()]

    def add_vote(self, vote: Vote):
        self.db.collection("votes").document(vote.id).set(vote.dict())


class Prompt(BaseModel):
    id: str
    text: str
    categories: List[str] = []
    start_image_url: Optional[str] = None
    end_image_url: Optional[str] = None
    reference_image_url: Optional[str] = None
    reference_images: Optional[List[str]] = None
    models: List[str] = ["Veo", "Kling", "Seedance"]
    status: str = "pending"
    timestamp: float

    def __init__(self, **data):
        if "category" in data:
            cat = data.pop("category")
            if cat and not data.get("categories"):
                data["categories"] = [cat]
        super().__init__(**data)


class PromptsManager:
    def __init__(self):
        from google.cloud import firestore
        self.db = firestore.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))

    @property
    def prompts(self):
        return {doc.id: Prompt(**doc.to_dict()) for doc in self.db.collection("prompts").stream()}

    def save_prompt(self, prompt: Prompt):
        self.db.collection("prompts").document(prompt.id).set(prompt.dict())

    def delete_prompt(self, prompt_id: str):
        doc_ref = self.db.collection("prompts").document(prompt_id)
        if doc_ref.get().exists:
            doc_ref.delete()
            return True
        return False

    def get_all(self):
        from google.cloud import firestore
        docs = self.db.collection("prompts").order_by("timestamp", direction=firestore.Query.DESCENDING).stream()
        return [Prompt(**doc.to_dict()) for doc in docs]


# Singletons
registry = RegistryManager()
jobs_manager = JobsManager()
votes_manager = VotesManager()
prompts_manager = PromptsManager()


# ===================================================================
# Auth
# ===================================================================
async def verify_admin(x_admin_user: str = Header(None), x_admin_pass: str = Header(None)):
    if x_admin_user != "admin" or x_admin_pass != "password":
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.post("/api/admin/login")
async def admin_login(creds: dict):
    if creds.get("username") == "admin" and creds.get("password") == "password":
        return {"status": "success"}
    raise HTTPException(status_code=401, detail="Invalid credentials")


# ===================================================================
# Model Registry Endpoints
# ===================================================================
@app.get("/api/models")
async def get_models():
    return list(registry.models.values())


@app.post("/api/models")
async def add_model(model: RegisteredModel):
    registry.add_model(model)
    return {"status": "success", "model": model}


@app.post("/api/models/{model_id}/toggle")
async def toggle_model(model_id: str):
    if registry.toggle_model(model_id):
        return {"status": "success", "is_active": registry.models[model_id].is_active}
    return {"status": "error", "message": "Model not found"}


@app.delete("/api/models/{model_id}")
async def delete_model(model_id: str):
    if model_id in registry.models:
        del registry.models[model_id]
        registry.save()
        return {"status": "success"}
    return {"status": "error", "message": "Model not found"}


# ===================================================================
# Prompt Management
# ===================================================================
@app.get("/api/admin/prompts")
async def get_admin_prompts():
    return prompts_manager.get_all()


@app.post("/api/admin/prompts")
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


@app.delete("/api/admin/prompts/{prompt_id}")
async def delete_admin_prompt(prompt_id: str):
    if prompts_manager.delete_prompt(prompt_id):
        return {"status": "success"}
    return {"status": "error", "message": "Prompt not found"}


# ===================================================================
# Image Generation & Upload
# ===================================================================
@app.post("/api/generate-image")
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


@app.post("/api/upload")
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


# ===================================================================
# Tags
# ===================================================================
@app.post("/api/admin/generate-tags")
async def generate_tags_endpoint(request: dict):
    tags = await generate_tags_with_gemini(
        request.get("text", ""),
        request.get("start_image_url"),
        request.get("end_image_url"),
        request.get("reference_images"),
    )
    return {"status": "success", "tags": tags}


@app.get("/api/tags")
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


@app.post("/api/admin/backfill-tags")
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


# ===================================================================
# Sheets integration
# ===================================================================
from util.sheets_utils import read_sheet, update_sheet_row


class SheetLoadRequest(BaseModel):
    url: str


class SheetUpdateRequest(BaseModel):
    url: str
    row: int
    success: bool
    error: str = ""


@app.post("/api/admin/batch/sheet/load")
async def load_batch_sheet(req: SheetLoadRequest):
    try:
        data = read_sheet(req.url)
        return {"status": "success", "rows": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/admin/batch/sheet/update")
async def update_batch_sheet(req: SheetUpdateRequest):
    try:
        update_sheet_row(req.url, req.row, req.success, req.error)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===================================================================
# Admin Jobs view
# ===================================================================
@app.get("/api/admin/jobs")
async def get_admin_jobs():
    jobs = jobs_manager.get_all()
    results_list = []
    for job in jobs:
        d = job.dict()
        # Sign input images
        for key in ("start_image_url", "end_image_url", "reference_image_url"):
            if d.get(key):
                d[key] = get_signed_url(normalize_gcs_url(d[key]))
        if d.get("reference_images"):
            d["reference_images"] = [get_signed_url(normalize_gcs_url(u)) for u in d["reference_images"]]
        # Sign result URLs
        for model_id, res in d["results"].items():
            if "url" in res and res["url"]:
                if res["url"].startswith("gs://") or f"storage.googleapis.com/{GCS_BUCKET_NAME}" in res["url"]:
                    res["url"] = get_signed_url(normalize_gcs_url(res["url"]))
            if "result" in res and isinstance(res["result"], dict) and "url" in res["result"] and res["result"]["url"]:
                if res["result"]["url"].startswith("gs://") or f"storage.googleapis.com/{GCS_BUCKET_NAME}" in res["result"]["url"]:
                    res["result"]["url"] = get_signed_url(normalize_gcs_url(res["result"]["url"]))
        results_list.append(d)
    return results_list


@app.delete("/api/admin/jobs/{job_id}")
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


@app.post("/api/admin/jobs/{job_id}/retry")
async def retry_failed_models(job_id: str, background_tasks: BackgroundTasks):
    """Retry only the failed/error models in a job."""
    from google.cloud import firestore as _fs
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
    doc_ref = db.collection("eval_jobs").document(job_id)
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Job not found")

    data = doc.to_dict()
    results = data.get("results", {})

    # Find models that errored
    failed_model_ids = [mid for mid, r in results.items() if r.get("status") == "error"]
    if not failed_model_ids:
        return {"status": "no_failures", "job_id": job_id, "message": "No failed models to retry"}

    # Look up registered models
    retry_models = [registry.models[mid] for mid in failed_model_ids if mid in registry.models]
    if not retry_models:
        raise HTTPException(status_code=400, detail=f"Failed models not found in registry: {failed_model_ids}")

    # Mark them as generating again
    for mid in failed_model_ids:
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
        model_ids=failed_model_ids,
    )

    background_tasks.add_task(_run_generation_background, job_id, retry_models, request, time.time())

    return {"status": "retrying", "job_id": job_id, "retrying_models": failed_model_ids}


@app.get("/api/admin/jobs/{job_id}/status")
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




# ===================================================================
# Video Generation
# ===================================================================
class PromptRequest(BaseModel):
    text: str
    categories: List[str] = []
    ratio: str = "16:9"
    prompt_id: Optional[str] = None
    start_image_url: Optional[str] = None
    end_image_url: Optional[str] = None
    reference_image_url: Optional[str] = None
    reference_images: Optional[List[str]] = None
    model_ids: Optional[List[str]] = None
    mode: Optional[str] = None

    def __init__(self, **data):
        # Migrate legacy single-category field
        if "category" in data:
            cat = data.pop("category")
            if cat and not data.get("categories"):
                data["categories"] = [cat]
        super().__init__(**data)


async def _auto_tag_job(job_id: str, prompt: str, start_image_url: str = None, end_image_url: str = None, reference_images: list = None):
    """Auto-generate tags for a job using Gemini, then persist them."""
    try:
        tags = await generate_tags_with_gemini(prompt, start_image_url, end_image_url, reference_images)
        job = jobs_manager.jobs.get(job_id)
        if job and not job.categories:
            job.categories = tags
            jobs_manager.save_job(job)
            print(f"Auto-tagged job {job_id}: {tags}")
    except Exception as e:
        print(f"Error auto-tagging job {job_id}: {e}")


async def _auto_tag_prompt(prompt_id: str, text: str, start_image_url: str = None, end_image_url: str = None, reference_images: list = None):
    """Auto-generate tags for a prompt using Gemini, then persist them."""
    try:
        tags = await generate_tags_with_gemini(text, start_image_url, end_image_url, reference_images)
        prompts = prompts_manager.prompts
        prompt = prompts.get(prompt_id)
        if prompt and not prompt.categories:
            prompt.categories = tags
            prompts_manager.save_prompt(prompt)
            print(f"Auto-tagged prompt {prompt_id}: {tags}")
    except Exception as e:
        print(f"Error auto-tagging prompt {prompt_id}: {e}")


async def _run_generation_background(job_id: str, target_models: List[RegisteredModel], request: PromptRequest, initiation_time: float):
    try:
        tasks = []
        model_keys = []

        for model in target_models:
            model_keys.append(model.id)
            if model.provider == "vertex":
                img_to_pass = request.start_image_url or request.reference_image_url
                if not img_to_pass and request.reference_images:
                    img_to_pass = request.reference_images[0]
                tasks.append(generate_with_veo(
                    request.text, request.ratio, img_to_pass, model.model_id,
                    request.reference_images, mode=model.type,
                ))
            elif model.provider == "fal":
                tasks.append(generate_with_fal(
                    model.model_id, request.text, request.ratio,
                    request.start_image_url or request.reference_image_url,
                    request.end_image_url, request.reference_images, mode=model.type,
                ))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        response_results = {}
        for i, key in enumerate(model_keys):
            res = results[i]
            if isinstance(res, Exception):
                response_results[key] = {"status": "error", "error": str(res)}
            else:
                if "latency" not in res:
                    res["latency"] = round(time.time() - initiation_time, 2)
                response_results[key] = res

        # Write results directly to Firestore to avoid stale cache issues.
        # The cache may have expired during the long generation (3-10 min),
        # causing jobs_manager.jobs.get() to return None and silently drop results.
        from google.cloud import firestore as _fs
        db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
        doc_ref = db.collection("eval_jobs").document(job_id)
        doc = doc_ref.get()
        if doc.exists:
            current = doc.to_dict()
            existing_results = current.get("results", {})
            for k, v in response_results.items():
                existing_results[k] = v
            doc_ref.update({"results": existing_results})
            jobs_manager.invalidate_cache()
            print(f"Background Job {job_id} completed. Updated {len(response_results)} model(s).")
        else:
            print(f"ERROR: Job {job_id} not found in Firestore after generation.")
    except Exception as e:
        print(f"Error in background generation for job {job_id}: {e}")
        # Try to mark failed models as error in Firestore
        try:
            from google.cloud import firestore as _fs
            db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
            doc_ref = db.collection("eval_jobs").document(job_id)
            doc = doc_ref.get()
            if doc.exists:
                current = doc.to_dict()
                existing_results = current.get("results", {})
                for key in model_keys:
                    if existing_results.get(key, {}).get("status") == "generating":
                        existing_results[key] = {"status": "error", "error": str(e)}
                doc_ref.update({"results": existing_results})
                jobs_manager.invalidate_cache()
        except Exception:
            pass


@app.post("/api/generate")
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
        all_requested = [registry.models[mid] for mid in request.model_ids if mid in registry.models]
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
        # Merge new model slots into the existing job's results
        for m in target_models:
            if m.id not in existing_job.results or existing_job.results[m.id].get("status") == "error":
                existing_job.results[m.id] = {"status": "generating"}
        jobs_manager.save_job(existing_job)
        job_id = existing_job.id

        background_tasks.add_task(_run_generation_background, job_id, target_models, request, initiation_time)

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


# ===================================================================
# Evaluation / Voting
# ===================================================================

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


@app.get("/api/evaluation/pair")
async def get_random_eval_pair(
    prompt_id: Optional[str] = None,
    tag: Optional[str] = None,
    search: Optional[str] = None,
):
    """
    Returns a random pair of successful variants for SxS evaluation.
    Supports filtering by prompt_id, tag (category), or free-text search on prompt.
    """
    groups = defaultdict(dict)

    for job in jobs_manager.jobs.values():
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
        if len(accessible) >= 2:
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


@app.post("/api/evaluation/vote")
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


@app.post("/api/admin/votes/prune")
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


# ===================================================================
# Stats & Leaderboard
# ===================================================================
@app.get("/api/evaluation/stats")
async def get_stats(ldap: Optional[str] = Query(None), tag: Optional[str] = Query(None)):
    """Win rates and leaderboard. Optionally filter by tag and/or ldap."""

    def _compute_leaderboard(v_list):
        skus = {}
        modes = {"T2V": 0, "I2V": 0, "R2V": 0}
        total_evals = len(v_list)

        # Average latency per model
        model_latencies = {}
        for job in jobs_manager.jobs.values():
            if tag and tag.lower() not in [c.lower() for c in job.categories]:
                continue
            for mid, res in job.results.items():
                if isinstance(res, dict) and res.get("status") != "error" and "latency" in res:
                    v_len = 4 if "seedance" in mid.lower() else 5
                    lps = res["latency"] / v_len
                    model_latencies.setdefault(mid, {"sum": 0, "count": 0})
                    model_latencies[mid]["sum"] += lps
                    model_latencies[mid]["count"] += 1

        for vote in v_list:
            job = jobs_manager.jobs.get(vote.job_id)

            # If tag filter is active, skip votes for non-matching jobs
            if tag and job and tag.lower() not in [c.lower() for c in job.categories]:
                continue

            mode = "T2V"
            if job:
                if job.reference_images and len(job.reference_images) > 0:
                    mode = "R2V"
                elif job.start_image_url or job.reference_image_url:
                    mode = "I2V"
            modes[mode] += 1

            for model_id in (vote.winner_model, vote.loser_model):
                if model_id not in skus:
                    skus[model_id] = {
                        "global": {"wins": 0, "total": 0},
                        "T2V": {"wins": 0, "total": 0, "scores": []},
                        "I2V": {"wins": 0, "total": 0, "scores": []},
                        "R2V": {"wins": 0, "total": 0, "scores": []},
                    }

            skus[vote.winner_model]["global"]["wins"] += 1
            skus[vote.winner_model]["global"]["total"] += 1
            skus[vote.winner_model][mode]["wins"] += 1
            skus[vote.winner_model][mode]["total"] += 1
            if vote.scores:
                skus[vote.winner_model][mode]["scores"].append(vote.scores)

            skus[vote.loser_model]["global"]["total"] += 1
            skus[vote.loser_model][mode]["total"] += 1

        def avg_scores(score_list):
            if not score_list:
                return {}
            sums, counts = {}, {}
            for s in score_list:
                for k, v in s.items():
                    # Skip scores of 5 — it is the default value and
                    # indicates the evaluator did not actively rate this
                    # criterion, which would skew averages.
                    if v == 5:
                        continue
                    sums[k] = sums.get(k, 0) + v
                    counts[k] = counts.get(k, 0) + 1
            return {k: round(sums[k] / counts[k], 2) for k in sums if counts.get(k)}

        leaderboard = []
        for mid, data in skus.items():
            g = data["global"]
            global_rate = (g["wins"] / g["total"]) * 100 if g["total"] else 0
            avg_lps = round(model_latencies[mid]["sum"] / model_latencies[mid]["count"], 2) if mid in model_latencies and model_latencies[mid]["count"] else 0

            entry = {
                "model_id": mid,
                "win_rate": round(global_rate, 1),
                "wins": g["wins"],
                "total": g["total"],
                "latency_ps": avg_lps,
            }
            for m in ("T2V", "I2V", "R2V"):
                mk = m.lower()
                d = data[m]
                rate = (d["wins"] / d["total"]) * 100 if d["total"] else 0
                entry[f"{mk}_rate"] = round(rate, 1)
                entry[f"{mk}_total"] = d["total"]
                entry[f"{mk}_wins"] = d["wins"]
                entry[f"{mk}_scores"] = avg_scores(d["scores"])
            leaderboard.append(entry)

        return {
            "total_evals": total_evals,
            "modes": modes,
            "skus": sorted(leaderboard, key=lambda x: x["win_rate"], reverse=True),
        }

    result = {"global": _compute_leaderboard(votes_manager.votes)}
    if ldap:
        user_votes = [v for v in votes_manager.votes if getattr(v, "ldap", "anonymous") == ldap]
        result["user"] = _compute_leaderboard(user_votes)
    return result


@app.get("/api/leaderboard/users")
async def get_user_leaderboard():
    counts = Counter()
    for v in votes_manager.votes:
        ldap = getattr(v, "ldap", "")
        if ldap and ldap != "anonymous":
            counts[ldap] += 1
    top_10 = sorted([{"ldap": k, "count": v} for k, v in counts.items()], key=lambda x: x["count"], reverse=True)[:10]
    return {"status": "success", "leaderboard": top_10}


# ===================================================================
# Health & Media Proxy
# ===================================================================
@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "service": "Project Pulse Backend"}


@app.get("/api/media")
async def get_media_proxy(url: str = Query(...)):
    try:
        from util.gcs_utils import download_blob_to_bytes
        data = download_blob_to_bytes(url)
        ct = "image/jpeg"
        url_lower = url.lower()
        if ".png" in url_lower:
            ct = "image/png"
        elif ".mp4" in url_lower:
            ct = "video/mp4"
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Length": str(len(data)),
            "Cache-Control": "public, max-age=3600",
        }
        return Response(content=data, media_type=ct, headers=headers)
    except Exception as e:
        print(f"Error proxying media {url}: {e}")
        raise HTTPException(status_code=404, detail="Failed to load media")


# ===================================================================
# Static files (Next.js export)
# ===================================================================
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    @app.exception_handler(404)
    async def custom_404_handler(request, exc):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        index_path = os.path.join(static_dir, "index.html")
        if os.path.exists(index_path):
            with open(index_path) as f:
                return HTMLResponse(content=f.read(), status_code=404)
        return HTMLResponse(content="Frontend not built", status_code=404)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
