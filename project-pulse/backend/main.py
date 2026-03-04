import os
import json
import asyncio
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from google.oauth2 import service_account
from dotenv import load_dotenv
import time
import fal_client

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
import logging
from pydantic import BaseModel

# Load environment variables
load_dotenv()

app = FastAPI(title="Project Pulse API")

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    # Try to safe-serialize the body or just skip it if it's complex (like FormData)
    body = exc.body
    if not isinstance(body, (dict, list, str, int, float, bool, type(None))):
        body = "<non-serializable body>"
        
    print(f"Validation Error: {exc.errors()}")
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body": body},
    )

# Configure CORS for Next.js frontend
# Use regex to be permissive for any localhost/127.0.0.1 variation
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def log_origin_middleware(request, call_next):
    origin = request.headers.get("origin")
    if origin:
        print(f"DEBUG: Request Origin: {origin} | Method: {request.method} | Path: {request.url.path}")
    response = await call_next(request)
    return response

# Initialize Google Cloud Project details
# Ensure we clear any problematic lingering environment variables
os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)

GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "vital-octagon-19612")
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "project-pulse")

print(f"DEBUG: Starting with Project ID: {GCP_PROJECT_ID}")

# Let Google libraries handle authentication via ADC automatically.
import asyncio
from typing import List, Dict, Optional
from providers.fal_provider import generate_with_fal
from providers.vertex_provider import generate_with_veo, generate_tags_with_gemini
from util.gcs_utils import upload_from_url, get_signed_url, normalize_gcs_url

class RegisteredModel(BaseModel):
    id: str  # Unique slug
    name: str
    provider: str  # 'fal' or 'vertex'
    model_id: str  # The actual API model string (e.g., 'fal-ai/kling-video')
    type: str = "t2v" # 't2v' or 'i2v'
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
        # Default models if none exist
        defaults = {
            "veo": RegisteredModel(id="veo", name="Veo 2.0", provider="vertex", model_id="veo-2.0-generate-001", type="i2v"),
         }
        return defaults

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
    category: Optional[str] = None # Legacy support

    def __init__(self, **data):
        if 'category' in data and not data.get('categories'):
            data['categories'] = [data['category']] if data['category'] else []
        super().__init__(**data)
    timestamp: float
    initiation_time: Optional[float] = None  # New: When the job was started
    prompt_id: Optional[str] = None          # New: Reference to a registered prompt
    start_image_url: Optional[str] = None    # New: Input reference images
    end_image_url: Optional[str] = None
    reference_image_url: Optional[str] = None
    reference_images: Optional[List[str]] = None # New: R2V support
    results: Dict[str, dict] # model_id -> result_obj

class JobsManager:
    def __init__(self):
        from google.cloud import firestore
        project_id = os.getenv("GCP_PROJECT_ID", "vital-octagon-19612")
        self.db = firestore.Client(project=project_id)
        self._cached_jobs = None
        self._last_fetch_time = 0
        self.CACHE_TTL = 300 # 5 minutes

    @property
    def jobs(self):
        # Fallback dictionary interface for read access using a 5-minute memory cache
        import time
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
        jobs = []
        for doc in docs:
            jobs.append(Job(**doc.to_dict()))
        return jobs

class Vote(BaseModel):
    id: str
    job_id: str
    winner_side: str # 'a' or 'b'
    winner_model: str
    loser_model: str
    scores: Dict[str, int]
    justification: str
    timestamp: float
    ldap: str = "anonymous"

class VotesManager:
    def __init__(self):
        from google.cloud import firestore
        project_id = os.getenv("GCP_PROJECT_ID", "vital-octagon-19612")
        self.db = firestore.Client(project=project_id)

    @property
    def votes(self):
        docs = self.db.collection("votes").stream()
        return [Vote(**doc.to_dict()) for doc in docs]

    def add_vote(self, vote: Vote):
        self.db.collection("votes").document(vote.id).set(vote.dict())

class Prompt(BaseModel):
    id: str
    text: str
    categories: List[str] = []
    category: Optional[str] = None # Legacy support

    def __init__(self, **data):
        if 'category' in data and not data.get('categories'):
            data['categories'] = [data['category']] if data['category'] else []
        super().__init__(**data)
    start_image_url: Optional[str] = None
    end_image_url: Optional[str] = None
    reference_image_url: Optional[str] = None
    reference_images: Optional[List[str]] = None
    models: List[str] = ["Veo", "Kling", "Seedance"] # Default for UI display
    status: str = "pending"
    timestamp: float

class PromptsManager:
    def __init__(self):
        from google.cloud import firestore
        project_id = os.getenv("GCP_PROJECT_ID", "vital-octagon-19612")
        self.db = firestore.Client(project=project_id)

    @property
    def prompts(self):
        docs = self.db.collection("prompts").stream()
        return {doc.id: Prompt(**doc.to_dict()) for doc in docs}

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

registry = RegistryManager()
jobs_manager = JobsManager()
votes_manager = VotesManager()
prompts_manager = PromptsManager()

# Simple Admin Auth
from fastapi import Header, HTTPException
async def verify_admin(x_admin_user: str = Header(None), x_admin_pass: str = Header(None)):
    if x_admin_user != "admin" or x_admin_pass != "password":
        raise HTTPException(status_code=401, detail="Unauthorized")

@app.post("/api/admin/login")
async def admin_login(creds: dict):
    if creds.get("username") == "admin" and creds.get("password") == "password":
        return {"status": "success"}
    raise HTTPException(status_code=401, detail="Invalid credentials")

def normalize_gcs_url(url: str) -> str:
    if not url:
        return url
    if "/api/media?url=" in url:
        import urllib.parse
        encoded = url.split("/api/media?url=")[-1]
        return urllib.parse.unquote(encoded)
    if ("X-Goog-Signature" in url or "?X-Goog-Algorithm" in url):
        return url.split("?")[0]
    return url

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

# --- Prompt Management ---

@app.get("/api/admin/prompts")
async def get_admin_prompts():
    return prompts_manager.get_all()

@app.post("/api/generate-image")
async def generate_image_api(request: dict):
    prompt = request.get("prompt")
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt is required")
    
    # Use Flux Schnell on FAL for fast generation
    try:
        result = await fal_client.run_async(
            "fal-ai/flux/schnell",
            arguments={"prompt": prompt, "image_size": "landscape_16_9"}
        )
        image_url = result["images"][0]["url"]
        
        # Upload to GCS
        filename = f"gen_img_{int(time.time())}.png"
        gcs_url = upload_from_url(image_url, filename)
        signed_url = get_signed_url(gcs_url) if gcs_url else image_url
        
        return {"status": "success", "url": signed_url, "raw_url": gcs_url or image_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/upload")
async def upload_file_api(file: UploadFile = File(...)):
    print(f"DEBUG: Received upload request for file: {file.filename}")
    try:
        # Sanitize filename to avoid signing issues with spaces/special chars
        safe_filename = "".join(c for c in file.filename if c.isalnum() or c in "._-").replace(" ", "_")
        if not safe_filename:
            safe_filename = "file"
        filename = f"uploads/{int(time.time())}_{safe_filename}"
        
        # Read file content
        content = await file.read()
        
        # Upload to GCS
        from util.gcs_utils import upload_from_bytes
        gcs_url = upload_from_bytes(content, filename, content_type=file.content_type)
        
        signed_url = get_signed_url(gcs_url)
        return {"status": "success", "url": signed_url, "raw_url": gcs_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/prompts")
async def add_admin_prompt(req: dict):
    prompt_id = req.get("id") or f"prompt_{int(time.time())}"
    prompt = Prompt(
        id=prompt_id,
        text=req["text"],
        category=req["category"],
        start_image_url=normalize_gcs_url(req.get("start_image_url")),
        end_image_url=normalize_gcs_url(req.get("end_image_url")),
        reference_image_url=normalize_gcs_url(req.get("reference_image_url")),
        reference_images=[normalize_gcs_url(u) for u in req.get("reference_images", [])] if req.get("reference_images") else None,
        models=req.get("models", ["Veo", "Kling", "Seedance"]),
        status=req.get("status", "pending"),
        timestamp=time.time()
    )
    prompts_manager.save_prompt(prompt)
    return {"status": "success", "prompt": prompt}

@app.delete("/api/admin/prompts/{prompt_id}")
async def delete_admin_prompt(prompt_id: str):
    if prompts_manager.delete_prompt(prompt_id):
        return {"status": "success"}
    return {"status": "error", "message": "Prompt not found"}

class PromptRequest(BaseModel):
    text: str
    categories: List[str] = []
    category: Optional[str] = None # Legacy support

    def __init__(self, **data):
        if 'category' in data and not data.get('categories'):
            data['categories'] = [data['category']]
        super().__init__(**data)
    prompt_id: Optional[str] = None # Link to a saved prompt if applicable
    ratio: str = "16:9"
    start_image_url: Optional[str] = None
    end_image_url: Optional[str] = None
    reference_image_url: Optional[str] = None
    reference_images: Optional[List[str]] = None # Supports R2V with multiple references
    model_ids: Optional[List[str]] = None # Allow choosing models
    mode: Optional[str] = None # 't2v', 'i2v', or 'r2v'

@app.get("/api/admin/jobs")
async def get_admin_jobs():
    jobs = jobs_manager.get_all()
    # We return a list of dicts to avoid modifying the in-memory Job objects directly or at least ensure normalization
    results_list = []
    for job in jobs:
        # Create a copy for the response
        job_dict = job.dict()
        
        # Sign input images
        if job_dict.get("start_image_url"):
            job_dict["start_image_url"] = get_signed_url(normalize_gcs_url(job_dict["start_image_url"]))
        if job_dict.get("end_image_url"):
            job_dict["end_image_url"] = get_signed_url(normalize_gcs_url(job_dict["end_image_url"]))
        if job_dict.get("reference_image_url"):
            job_dict["reference_image_url"] = get_signed_url(normalize_gcs_url(job_dict["reference_image_url"]))
        if job_dict.get("reference_images"):
            job_dict["reference_images"] = [get_signed_url(normalize_gcs_url(u)) for u in job_dict["reference_images"]]
            
        # Sign results
        for model_id, res in job_dict["results"].items():
            if "url" in res and res["url"]:
                # Keep original gs:// or stale https links and sign them fresh
                if res["url"].startswith("gs://") or f"storage.googleapis.com/{GCS_BUCKET_NAME}" in res["url"]:
                    res["url"] = get_signed_url(normalize_gcs_url(res["url"]))
            if "result" in res and isinstance(res["result"], dict) and "url" in res["result"] and res["result"]["url"]:
                if res["result"]["url"].startswith("gs://") or f"storage.googleapis.com/{GCS_BUCKET_NAME}" in res["result"]["url"]:
                    res["result"]["url"] = get_signed_url(normalize_gcs_url(res["result"]["url"]))
        results_list.append(job_dict)
    return results_list

from fastapi import Header, HTTPException, BackgroundTasks

async def _run_generation_background(job_id: str, target_models: List[RegisteredModel], request: PromptRequest, initiation_time: float):
    """
    Background worker that runs the actual generation and updates the job status.
    """
    try:
        tasks = []
        model_keys = []

        for model in target_models:
            model_keys.append(model.id)
            if model.provider == "vertex":
                # For Vertex, we prioritize start_image_url, then first reference if any
                img_to_pass = request.start_image_url or request.reference_image_url
                if not img_to_pass and request.reference_images:
                    img_to_pass = request.reference_images[0]
                
                tasks.append(generate_with_veo(
                    request.text, 
                    request.ratio, 
                    img_to_pass, 
                    model.model_id,
                    request.reference_images,
                    mode=model.type
                ))
            elif model.provider == "fal":
                # For FAL, we pass everything and let the provider handle logic
                tasks.append(generate_with_fal(
                    model.model_id, 
                    request.text, 
                    request.ratio, 
                    request.start_image_url or request.reference_image_url,
                    request.end_image_url,
                    request.reference_images,
                    mode=model.type
                ))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        response_results = {}
        for i, key in enumerate(model_keys):
            res = results[i]
            if isinstance(res, Exception):
                response_results[key] = {"status": "error", "error": str(res)}
            else:
                # Add latency info if provider didn't
                if "latency" not in res:
                    res["latency"] = round(time.time() - initiation_time, 2)
                response_results[key] = res

        # Update job entry with results
        # We need to re-load the job to avoid overwriting other potential updates (though rare in this case)
        job = jobs_manager.jobs.get(job_id)
        if job:
            job.results = response_results
            jobs_manager.save_job(job)
            print(f"✅ Background Job {job_id} completed.")
            
    except Exception as e:
        print(f"Error in background generation for job {job_id}: {e}")
        # Optionally mark job as error if needed

@app.post("/api/admin/generate-tags")
async def generate_tags(request: PromptRequest):
    """
    Suggests 3 tags based on the prompt and images using Gemini.
    """
    tags = await generate_tags_with_gemini(
        request.text,
        request.start_image_url,
        request.end_image_url,
        request.reference_images
    )
    return {"status": "success", "tags": tags}

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
        # Starting from row 2 (skipping header) - though we can just return all
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

@app.post("/api/generate")
async def generate_videos(request: PromptRequest, background_tasks: BackgroundTasks):
    """
    Triggers parallel generation across selected or active models in the background.
    Returns a job_id immediately.
    """
    initiation_time = time.time()
    
    # Infer mode if not explicitly provided
    mode = request.mode
    if not mode:
        if request.reference_images and len(request.reference_images) > 0:
            mode = "r2v"
        elif request.start_image_url or request.reference_image_url:
            mode = "i2v"
        else:
            mode = "t2v"
    
    print(f"DEBUG: Processing generation in mode: {mode}")

    target_models = []
    if request.model_ids:
        # Use requested models but STILL filter by the correct mode
        all_requested = [registry.models[mid] for mid in request.model_ids if mid in registry.models]
        target_models = [m for m in all_requested if m.type == mode]
    else:
        # Get active models for this specific mode
        target_models = [m for m in registry.get_active_models() if m.type == mode]

    if not target_models:
        print(f"WARNING: No active models found for mode {mode}")
        # Optionally fallback to all active models if we really want to generate something, 
        # but user asked for strict filtering.
        # return {"status": "error", "message": f"No active models for mode {mode}"}

    job_id = f"job_{int(time.time() * 1000)}"
    prompt_id = request.prompt_id or job_id
    
    # Create and save initial job entry with "generating" status for selected models
    initial_results = {m.id: {"status": "generating"} for m in target_models}
    
    # Normalize incoming URLs so backend models receive raw gs://
    request.start_image_url = normalize_gcs_url(request.start_image_url)
    request.end_image_url = normalize_gcs_url(request.end_image_url)
    request.reference_image_url = normalize_gcs_url(request.reference_image_url)
    if request.reference_images:
        request.reference_images = [normalize_gcs_url(u) for u in request.reference_images]

    job = Job(
        id=job_id,
        prompt=request.text,
        prompt_id=prompt_id,
        categories=request.categories,
        timestamp=time.time(),
        initiation_time=initiation_time,
        start_image_url=request.start_image_url,
        end_image_url=request.end_image_url,
        reference_image_url=request.reference_image_url,
        reference_images=request.reference_images,
        results=initial_results
    )
    jobs_manager.save_job(job)
    
    # Add generation to background tasks
    background_tasks.add_task(_run_generation_background, job_id, target_models, request, initiation_time)

    return {
        "job_id": job_id,
        "prompt": request.text,
        "status": "queued",
        "initiation_time": initiation_time
    }

import random
import asyncio
import requests

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
    
    # Sign GCS URLs on the fly for UI
    if url and (url.startswith("gs://") or "storage.googleapis.com" in url):
        if "X-Goog-Signature" not in url:
            return get_signed_url(url)
    return url

def _is_url_accessible(url):
    if not url: return False
    try:
        from util.gcs_utils import https_to_gs, get_upload_client
        
        check_url = url
        if "/api/media?url=" in check_url:
            import urllib.parse
            check_url = urllib.parse.unquote(check_url.split("/api/media?url=")[-1])
            
        check_url = https_to_gs(check_url)
        if check_url.startswith("gs://"):
            client = get_upload_client()
            bucket_name = check_url.split("gs://")[1].split("/")[0]
            blob_name = check_url.split(f"gs://{bucket_name}/")[1]
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(blob_name)
            return blob.exists()
            
        # Fallback to HTTP check for non-GCS URLs
        resp = requests.get(url, timeout=3, stream=True)
        return resp.status_code == 200
    except Exception as e:
        print(f"Error checking url access: {e}")
        return False

@app.get("/api/evaluation/pair")
async def get_random_eval_pair(prompt_id: Optional[str] = None):
    """
    Returns a random pair of successful variants for the same prompt matching across jobs.
    Group by prompt_id first, then prompt text if id not present.
    """
    from collections import defaultdict
    import random
    
    # groups shape: { group_key: { model_id: (job, url) } }
    groups = defaultdict(dict)
    
    for job in jobs_manager.jobs.values():
        group_key = getattr(job, "prompt_id", None) or job.prompt
        
        # Grab successful models from this job
        for mid, res in job.results.items():
            if res.get("status") == "success":
                url = _extract_url(res)
                if url:
                    groups[group_key][mid] = (job, url)
                    
    # Filter for groups with >=2 distinct models
    valid_groups = {k: v for k, v in groups.items() if len(v) >= 2}
    
    if prompt_id:
        # filter specifically for this prompt_id
        filtered_groups = {k: v for k, v in valid_groups.items() if str(k) == str(prompt_id)}
        if filtered_groups:
            valid_groups = filtered_groups
    
    if not valid_groups:
        return {"status": "error", "message": "Could not find any prompt with at least two successful models."}
        
    group_keys = list(valid_groups.keys())
    random.shuffle(group_keys)
    
    max_attempts = 20
    attempts = 0
    
    while attempts < max_attempts and attempts < len(group_keys):
        g_key = group_keys[attempts]
        attempts += 1
        
        candidates = valid_groups[g_key] # { model_id: (job, url) }
        
        # Gather all distinct models and their fully verified accessible URLs
        accessible_variants = []
        for mid, (job, url) in candidates.items():
            if _is_url_accessible(url):
                accessible_variants.append((mid, job, url))
                
        if len(accessible_variants) >= 2:
            # We found a winner!
            pair = random.sample(accessible_variants, 2)
            side_a_model, job_a, url_a = pair[0]
            side_b_model, job_b, url_b = pair[1]
            
            # Use job_a's metadata since by grouping definition the prompt inputs are equal
            return {
                "job_id": getattr(job_a, "prompt_id", None) or job_a.id,
                "prompt": job_a.prompt,
                "category": getattr(job_a, "category", None),
                "categories": getattr(job_a, "categories", None),
                "start_image_url": get_signed_url(job_a.start_image_url) if getattr(job_a, "start_image_url", None) else None,
                "end_image_url": get_signed_url(job_a.end_image_url) if getattr(job_a, "end_image_url", None) else None,
                "reference_image_url": get_signed_url(job_a.reference_image_url) if getattr(job_a, "reference_image_url", None) else None,
                "reference_images": [get_signed_url(u) for u in job_a.reference_images] if getattr(job_a, "reference_images", None) else None,
                "variant_a": {
                    "model_id": side_a_model,
                    "url": url_a
                },
                "variant_b": {
                    "model_id": side_b_model,
                    "url": url_b
                }
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
        id=vote_id,
        job_id=req.job_id,
        winner_side=req.winner_side,
        winner_model=req.winner_model,
        loser_model=req.loser_model,
        scores=req.scores,
        justification=req.justification,
        timestamp=time.time(),
        ldap=req.ldap
    )
    votes_manager.add_vote(vote)
    return {"status": "success", "vote_id": vote_id}

from fastapi import Query

@app.get("/api/evaluation/stats")
async def get_stats(ldap: Optional[str] = Query(None)):
    """
    Aggregates win rates and leaderboard info.
    """
    def _compute_leaderboard(v_list):
        skus = {}
        modes = {"T2V": 0, "I2V": 0, "R2V": 0}
        total_evals = len(v_list)
        
        # Pre-compute global average latency-per-sec for each model
        model_latencies = {}
        for job in jobs_manager.jobs.values():
            if not getattr(job, "results", None): continue
            for mid, res in job.results.items():
                if isinstance(res, dict) and res.get("status") != "error" and "latency" in res:
                    v_len = 5 # default 5s (Kling, Veo)
                    if "seedance" in mid.lower(): v_len = 4
                    lps = res["latency"] / v_len
                    if mid not in model_latencies:
                        model_latencies[mid] = {"sum": 0, "count": 0}
                    model_latencies[mid]["sum"] += lps
                    model_latencies[mid]["count"] += 1
        
        for vote in v_list:
            job = jobs_manager.jobs.get(vote.job_id)
            mode = "T2V"
            if job:
                if job.reference_images and len(job.reference_images) > 0:
                    mode = "R2V"
                elif job.start_image_url or job.reference_image_url:
                    mode = "I2V"
                    
            modes[mode] += 1
            
            if vote.winner_model not in skus:
                skus[vote.winner_model] = {"global": {"wins": 0, "total": 0}, "T2V": {"wins": 0, "total": 0, "scores": []}, "I2V": {"wins": 0, "total": 0, "scores": []}, "R2V": {"wins": 0, "total": 0, "scores": []}}
            if vote.loser_model not in skus:
                skus[vote.loser_model] = {"global": {"wins": 0, "total": 0}, "T2V": {"wins": 0, "total": 0, "scores": []}, "I2V": {"wins": 0, "total": 0, "scores": []}, "R2V": {"wins": 0, "total": 0, "scores": []}}
                
            skus[vote.winner_model]["global"]["wins"] += 1
            skus[vote.winner_model]["global"]["total"] += 1
            skus[vote.winner_model][mode]["wins"] += 1
            skus[vote.winner_model][mode]["total"] += 1
            if vote.scores:
                skus[vote.winner_model][mode]["scores"].append(vote.scores)
            
            skus[vote.loser_model]["global"]["total"] += 1
            skus[vote.loser_model][mode]["total"] += 1

        leaderboard = []
        for mid, data in skus.items():
            global_rate = (data["global"]["wins"] / data["global"]["total"]) * 100 if data["global"]["total"] > 0 else 0
            t2v_rate = (data["T2V"]["wins"] / data["T2V"]["total"]) * 100 if data["T2V"]["total"] > 0 else 0
            i2v_rate = (data["I2V"]["wins"] / data["I2V"]["total"]) * 100 if data["I2V"]["total"] > 0 else 0
            r2v_rate = (data["R2V"]["wins"] / data["R2V"]["total"]) * 100 if data["R2V"]["total"] > 0 else 0
            
            avg_lps = round(model_latencies[mid]["sum"] / model_latencies[mid]["count"], 2) if mid in model_latencies and model_latencies[mid]["count"] > 0 else 0
            
            def avg_scores(score_list):
                if not score_list: return {}
                sums = {}
                counts = {}
                for s in score_list:
                    for k, v in s.items():
                        sums[k] = sums.get(k, 0) + v
                        counts[k] = counts.get(k, 0) + 1
                return {k: round(sums[k] / counts[k], 2) for k in sums}
            
            leaderboard.append({
                "model_id": mid,
                "win_rate": round(global_rate, 1),
                "wins": data["global"]["wins"],
                "total": data["global"]["total"],
                "t2v_rate": round(t2v_rate, 1),
                "t2v_total": data["T2V"]["total"],
                "t2v_wins": data["T2V"]["wins"],
                "t2v_scores": avg_scores(data["T2V"]["scores"]),
                "i2v_rate": round(i2v_rate, 1),
                "i2v_total": data["I2V"]["total"],
                "i2v_wins": data["I2V"]["wins"],
                "i2v_scores": avg_scores(data["I2V"]["scores"]),
                "r2v_rate": round(r2v_rate, 1),
                "r2v_total": data["R2V"]["total"],
                "r2v_wins": data["R2V"]["wins"],
                "r2v_scores": avg_scores(data["R2V"]["scores"]),
                "latency_ps": avg_lps
            })
            
        return {
            "total_evals": total_evals,
            "modes": modes,
            "skus": sorted(leaderboard, key=lambda x: x["win_rate"], reverse=True)
        }

    result = {
        "global": _compute_leaderboard(votes_manager.votes)
    }
    
    if ldap:
        user_votes = [v for v in votes_manager.votes if getattr(v, "ldap", "anonymous") == ldap]
        result["user"] = _compute_leaderboard(user_votes)
        
    return result

@app.get("/api/leaderboard/users")
async def get_user_leaderboard():
    from collections import Counter
    counts = Counter()
    for v in votes_manager.votes:
        ldap = getattr(v, "ldap", "")
        if ldap and ldap != "anonymous":
            counts[ldap] += 1
            
    top_10 = sorted([{"ldap": k, "count": v} for k,v in counts.items()], key=lambda x: x["count"], reverse=True)[:10]
    return {"status": "success", "leaderboard": top_10}

@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "service": "Project Pulse Backend"}

from fastapi import Query, Response

@app.get("/api/media")
async def get_media_proxy(url: str = Query(...)):
    """
    Proxies GCS assets avoiding the need for V4 signed URLs.
    Uses backend ADC to read and serve to the UI.
    """
    try:
        from util.gcs_utils import download_blob_to_bytes
        data = download_blob_to_bytes(url)
        
        ct = "image/jpeg"
        url_lower = url.lower()
        if ".png" in url_lower: ct = "image/png"
        elif ".mp4" in url_lower: ct = "video/mp4"
        
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Length": str(len(data)),
            "Cache-Control": "public, max-age=3600",
        }
        return Response(content=data, media_type=ct, headers=headers)
    except Exception as e:
        print(f"Error proxying media {url}: {e}")
        raise HTTPException(status_code=404, detail="Failed to load media")

from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import os

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
    uvicorn.run("main:app", host="0.0.0.0", port=8010, reload=True)
