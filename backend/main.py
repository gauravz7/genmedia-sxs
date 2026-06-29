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

from fastapi import FastAPI, HTTPException, UploadFile, File, Header, BackgroundTasks, Query, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

from providers.fal_provider import generate_with_fal
from providers.vertex_provider import generate_with_veo, generate_tags_with_gemini, translate_to_english
from providers.omni_provider import generate_with_omni
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
# Isolated test database for the SxS (Seedance vs Omni) feature — kept separate
# from the production `eval_jobs` / `votes` collections.
SXS_COLLECTION = os.getenv("SXS_COLLECTION", "sxs_jobs")
SXS_VOTES_COLLECTION = os.getenv("SXS_VOTES_COLLECTION", "sxs_votes")
SXS_RUNS_COLLECTION = os.getenv("SXS_RUNS_COLLECTION", "sxs_runs")

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
    provider: str       # 'fal', 'vertex', or 'omni'
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
    reference_videos: Optional[List[str]] = None
    results: Dict[str, dict]
    generation_history: Dict[str, list] = {}
    # SxS auto-eval fields (source == "sxs_auto")
    source: Optional[str] = None
    batch_id: Optional[str] = None
    customer: Optional[str] = None
    modality: Optional[str] = None
    duration: Optional[int] = None
    auto_evals: Dict[str, dict] = {}
    auto_eval_status: Optional[str] = None
    auto_eval_error: Optional[str] = None

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
# Auth — token-based admin gate
# ===================================================================
import hashlib
import hmac

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS")
_ADMIN_TOKEN_SALT = "project-pulse-sxs:v1"


def _admin_token() -> Optional[str]:
    """Stateless admin token derived from ADMIN_PASS. None if unset."""
    if not ADMIN_PASS:
        return None
    return hashlib.sha256(f"{_ADMIN_TOKEN_SALT}:{ADMIN_USER}:{ADMIN_PASS}".encode()).hexdigest()


async def require_admin(x_admin_token: str = Header(None)):
    """FastAPI dependency: gate mutating/expensive endpoints behind admin login."""
    expected = _admin_token()
    if not expected:
        raise HTTPException(status_code=500, detail="ADMIN_PASS not configured on server")
    if not x_admin_token or not hmac.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=401, detail="Admin authentication required")


@app.post("/api/admin/login")
async def admin_login(creds: dict):
    if not ADMIN_PASS:
        raise HTTPException(status_code=500, detail="ADMIN_PASS not configured")
    if creds.get("username") == ADMIN_USER and creds.get("password") == ADMIN_PASS:
        return {"status": "success", "token": _admin_token()}
    raise HTTPException(status_code=401, detail="Invalid credentials")


# ===================================================================
# Model Registry Endpoints
# ===================================================================
@app.get("/api/models")
async def get_models():
    return list(registry.models.values())


@app.post("/api/models", dependencies=[Depends(require_admin)])
async def add_model(model: RegisteredModel):
    registry.add_model(model)
    return {"status": "success", "model": model}


@app.post("/api/models/{model_id}/toggle", dependencies=[Depends(require_admin)])
async def toggle_model(model_id: str):
    if registry.toggle_model(model_id):
        return {"status": "success", "is_active": registry.models[model_id].is_active}
    return {"status": "error", "message": "Model not found"}


@app.delete("/api/models/{model_id}", dependencies=[Depends(require_admin)])
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


@app.post("/api/admin/prompts", dependencies=[Depends(require_admin)])
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


@app.delete("/api/admin/prompts/{prompt_id}", dependencies=[Depends(require_admin)])
async def delete_admin_prompt(prompt_id: str):
    if prompts_manager.delete_prompt(prompt_id):
        return {"status": "success"}
    return {"status": "error", "message": "Prompt not found"}


# ===================================================================
# Image Generation & Upload
# ===================================================================
@app.post("/api/generate-image", dependencies=[Depends(require_admin)])
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


@app.post("/api/upload", dependencies=[Depends(require_admin)])
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
# SxS Studio — Seedance 2.0 vs Gemini Omni (JSON-driven gen + auto-eval)
# ===================================================================
def _sign_sxs_job(d: dict) -> dict:
    """Sign result + input-asset GCS URLs of an SxS job doc for the browser."""
    def _sign(u):
        if not u:
            return u
        if u.startswith("gs://") or "storage.googleapis.com" in u:
            return get_signed_url(normalize_gcs_url(u))
        return u
    for key in ("reference_images", "reference_videos"):
        if d.get(key):
            d[key] = [_sign(u) for u in d[key]]
    for _mid, res in (d.get("results") or {}).items():
        if isinstance(res, dict):
            if res.get("url"):
                res["url"] = _sign(res["url"])
            if isinstance(res.get("result"), dict) and res["result"].get("url"):
                res["result"]["url"] = _sign(res["result"]["url"])
    return d


@app.post("/api/sxs/upload", dependencies=[Depends(require_admin)])
async def sxs_upload(
    background_tasks: BackgroundTasks,
    cases: UploadFile = File(...),
    files: List[UploadFile] = File(default=[]),
):
    """Upload a cases JSON + local asset files; create one job per case and
    schedule background Seedance+Omni generation followed by Core-5 auto-eval."""
    from util.asset_intake import (
        save_uploads_to_temp,
        upload_assets_to_gcs,
        rewrite_case_assets,
    )
    from sxs_pipeline import create_sxs_job, process_batch

    try:
        raw = await cases.read()
        parsed = json.loads(raw.decode("utf-8"))
        case_list = parsed.get("cases", parsed) if isinstance(parsed, dict) else parsed
        if not isinstance(case_list, list) or not case_list:
            raise ValueError("cases JSON must be a non-empty array of case objects")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid cases JSON: {e}")

    batch_id = f"batch_{int(time.time())}"

    # Stage uploaded asset files and push them to GCS, then rewrite relative paths.
    uploaded = []
    for f in files or []:
        data = await f.read()
        uploaded.append(type("U", (), {"filename": f.filename, "bytes": data})())
    relpath_to_url = {}
    if uploaded:
        base_dir = save_uploads_to_temp(uploaded)
        relpath_to_url = upload_assets_to_gcs(base_dir, batch_id)

    pairs = []
    for case in case_list:
        rewritten = rewrite_case_assets(case, relpath_to_url) if relpath_to_url else case
        job_id = create_sxs_job(rewritten, batch_id=batch_id)
        pairs.append((job_id, rewritten))

    background_tasks.add_task(process_batch, pairs)
    jobs_manager.invalidate_cache()

    return {
        "status": "queued",
        "batch_id": batch_id,
        "job_ids": [jid for jid, _ in pairs],
        "count": len(pairs),
    }


@app.get("/api/sxs/jobs")
async def sxs_list_jobs(batch: Optional[str] = Query(None)):
    """List SxS auto-eval jobs (optionally filtered by batch), signed for browser."""
    from google.cloud import firestore as _fs
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
    q = db.collection(SXS_COLLECTION).where("source", "==", "sxs_auto")
    docs = list(q.stream())
    out = []
    for doc in docs:
        d = doc.to_dict()
        d["id"] = doc.id
        if batch and d.get("batch_id") != batch:
            continue
        out.append(_sign_sxs_job(d))
    out.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    return out


@app.get("/api/sxs/jobs/{job_id}")
async def sxs_get_job(job_id: str):
    from google.cloud import firestore as _fs
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
    doc = db.collection(SXS_COLLECTION).document(job_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Job not found")
    d = doc.to_dict()
    d["id"] = doc.id
    return _sign_sxs_job(d)


@app.delete("/api/sxs/jobs/{job_id}", dependencies=[Depends(require_admin)])
async def sxs_delete_job(job_id: str):
    """Delete an SxS pair from the isolated sxs_jobs collection."""
    from google.cloud import firestore as _fs
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
    ref = db.collection(SXS_COLLECTION).document(job_id)
    if not ref.get().exists:
        raise HTTPException(status_code=404, detail="Job not found")
    ref.delete()
    return {"status": "deleted", "job_id": job_id}


@app.post("/api/sxs/jobs/{job_id}/retry", dependencies=[Depends(require_admin)])
async def sxs_retry_job(job_id: str, background_tasks: BackgroundTasks):
    """Re-generate the failed model(s) of one SxS pair, then re-run auto-eval."""
    from google.cloud import firestore as _fs
    from sxs_pipeline import retry_job
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
    if not db.collection(SXS_COLLECTION).document(job_id).get().exists:
        raise HTTPException(status_code=404, detail="Job not found")
    background_tasks.add_task(retry_job, job_id)
    return {"status": "retrying", "job_id": job_id}


@app.get("/api/sxs/aieval/{job_id}")
async def sxs_get_aieval(job_id: str):
    """Return the auto-eval (Core-5) reports for a job — used to reveal AI
    ratings on the human-voting page AFTER a vote is cast."""
    from google.cloud import firestore as _fs
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
    # job_id from the voting page may be a prompt_id; resolve to the actual doc.
    doc = db.collection(SXS_COLLECTION).document(job_id).get()
    if not doc.exists:
        snaps = list(
            db.collection(SXS_COLLECTION).where("prompt_id", "==", job_id).stream()
        )
        if not snaps:
            raise HTTPException(status_code=404, detail="Job not found")
        d = snaps[0].to_dict()
    else:
        d = doc.to_dict()
    return {
        "auto_eval_status": d.get("auto_eval_status"),
        "auto_evals": d.get("auto_evals", {}),
    }


@app.get("/api/sxs/report.json")
async def sxs_report_json(batch: Optional[str] = Query(None)):
    data = await sxs_list_jobs(batch=batch)
    return data


@app.get("/api/sxs/report.csv")
async def sxs_report_csv(batch: Optional[str] = Query(None)):
    import csv
    import io
    jobs = await sxs_list_jobs(batch=batch)
    axes = [
        "prompt_adherence", "visual_quality", "motion_physics",
        "temporal_consistency", "audio_visual_sync",
    ]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["job_id", "customer", "case_id", "modality", "prompt", "model_key", "model"]
        + [a + "_score" for a in axes]
        + ["overall_score", "critical_flaws"]
    )
    for j in jobs:
        evals = j.get("auto_evals", {}) or {}
        for model_key, rep in evals.items():
            row = [
                j.get("id"), j.get("customer"), j.get("prompt_id"),
                j.get("modality"), (j.get("prompt") or "")[:500], model_key,
                (rep.get("model") or ""),
            ]
            for a in axes:
                ax = rep.get(a) or {}
                row.append(ax.get("score") if isinstance(ax, dict) else "")
            row.append(rep.get("overall_score"))
            row.append(" | ".join(rep.get("critical_flaws") or []))
            writer.writerow(row)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sxs_ai_ratings.csv"},
    )


@app.get("/api/sxs/pair")
async def sxs_pair(
    tag: Optional[str] = Query(None),
    prompt_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
):
    """Return a random Seedance-vs-Omni pair from the isolated SxS test DB for
    human voting. Optional filters: tag (category), prompt_id, search (prompt
    text). AI eval is fetched separately (only after a vote is cast)."""
    from google.cloud import firestore as _fs
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
    docs = list(db.collection(SXS_COLLECTION).where("source", "==", "sxs_auto").stream())

    tag_l = (tag or "").strip().lower()
    pid_l = (prompt_id or "").strip().lower()
    q_l = (search or "").strip().lower()

    def _u(res):
        u = res.get("url") or (res.get("result") or {}).get("url")
        if u and (u.startswith("gs://") or "storage.googleapis.com" in u):
            return get_signed_url(normalize_gcs_url(u))
        return u

    candidates = []
    for doc in docs:
        d = doc.to_dict()
        d["id"] = doc.id
        succ = {
            k: r for k, r in (d.get("results") or {}).items()
            if isinstance(r, dict) and r.get("status") == "success"
            and (r.get("url") or (r.get("result") or {}).get("url"))
        }
        if len(succ) < 2:
            continue
        if tag_l and tag_l not in [str(c).lower() for c in (d.get("categories") or [])]:
            continue
        if pid_l and pid_l not in str(d.get("prompt_id", "")).lower():
            continue
        if q_l and q_l not in str(d.get("prompt", "")).lower():
            continue
        candidates.append((d, succ))

    if not candidates:
        return {"status": "error", "message": "No SxS pairs ready for voting"}

    d, succ = random.choice(candidates)
    keys = list(succ.keys())
    random.shuffle(keys)
    a, b = keys[0], keys[1]

    def _sign(u):
        if u and (u.startswith("gs://") or "storage.googleapis.com" in u):
            return get_signed_url(normalize_gcs_url(u))
        return u

    return {
        "job_id": d["id"],
        "prompt": d.get("prompt"),
        "customer": d.get("customer"),
        "modality": d.get("modality"),
        "ratio": d.get("ratio", "16:9"),
        "reference_images": [_sign(u) for u in (d.get("reference_images") or [])],
        "reference_videos": [_sign(u) for u in (d.get("reference_videos") or [])],
        "variant_a": {"model_id": a, "url": _u(succ[a])},
        "variant_b": {"model_id": b, "url": _u(succ[b])},
    }


class SxsVoteRequest(BaseModel):
    job_id: str
    winner_side: str
    winner_model: str
    loser_model: str
    scores: Dict[str, int] = {}
    justification: str = ""
    ldap: str = "anonymous"


def _case_key(case: dict) -> str:
    """Stable identity for a case (used for dedup across runs)."""
    return f"{(case.get('customer') or '').strip()}|{(case.get('id') or case.get('prompt_id') or '').strip()}"


def _job_status(j: dict) -> str:
    """Classify an SxS job: 'done' (both models produced video), 'failed'
    (≥1 model errored / produced no result), or 'in_progress'."""
    results = j.get("results") or {}
    if not results:
        return "in_progress"
    statuses = [r.get("status") for r in results.values() if isinstance(r, dict)]
    success = sum(1 for s in statuses if s == "success")
    errored = sum(1 for s in statuses if s == "error")
    aes = j.get("auto_eval_status")
    if success >= len(results) and success >= 2:
        return "done"  # every model (both) produced a result
    if errored > 0 and aes in ("done", "error"):
        return "failed"  # at least one API produced no result, generation settled
    return "in_progress"


def _already_run_keys(db) -> Dict[str, str]:
    """Map case_key -> status across existing jobs. Only 'done' (both models
    produced video) is skipped on re-run; 'failed' and 'in_progress' remain
    re-runnable so a missing API result can be retried."""
    rank = {"in_progress": 0, "failed": 1, "done": 2}
    out: Dict[str, str] = {}
    for d in db.collection(SXS_COLLECTION).where("source", "==", "sxs_auto").stream():
        j = d.to_dict()
        key = f"{(j.get('customer') or '').strip()}|{(j.get('prompt_id') or '').strip()}"
        st = _job_status(j)
        if rank[st] >= rank.get(out.get(key, "in_progress"), 0):
            out[key] = st
    return out


def _load_cases_from_gcs(cases_uri: str) -> list:
    """Download + parse a cases JSON stored in GCS (gs:// or https URL)."""
    from util.gcs_utils import download_blob_to_bytes
    raw = download_blob_to_bytes(cases_uri)
    parsed = json.loads(raw.decode("utf-8"))
    cases = parsed.get("cases", parsed) if isinstance(parsed, dict) else parsed
    if not isinstance(cases, list):
        raise ValueError("cases JSON must be an array (or have a 'cases' array)")
    return cases


@app.get("/api/sxs/catalog")
async def sxs_catalog(cases_uri: str = Query(...)):
    """Return counts by customer and modality for a GCS cases JSON, so the UI
    can offer filters before launching a (potentially large) batch."""
    try:
        cases = _load_cases_from_gcs(cases_uri)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to load cases: {e}")
    customers: Dict[str, int] = {}
    modalities: Dict[str, int] = {}
    for c in cases:
        cu = c.get("customer") or "—"
        mo = c.get("modality") or c.get("mode") or "—"
        customers[cu] = customers.get(cu, 0) + 1
        modalities[mo] = modalities.get(mo, 0) + 1
    return {
        "cases_uri": cases_uri,
        "total": len(cases),
        "customers": dict(sorted(customers.items())),
        "modalities": dict(sorted(modalities.items())),
    }


@app.post("/api/sxs/retry-failures", dependencies=[Depends(require_admin)])
async def sxs_retry_failures(background_tasks: BackgroundTasks, limit: Optional[int] = Query(None)):
    """Retry every case where an API failed to produce a result. Regenerates
    only the failed model(s) per job, then re-runs the Core-5 auto-eval."""
    from google.cloud import firestore as _fs
    from sxs_pipeline import retry_failures
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))

    failed_ids = []
    for d in db.collection(SXS_COLLECTION).where("source", "==", "sxs_auto").stream():
        j = d.to_dict()
        results = j.get("results") or {}
        statuses = [r.get("status") for r in results.values() if isinstance(r, dict)]
        if not statuses:
            continue
        settled = j.get("auto_eval_status") in ("done", "error") or all(
            s in ("success", "error") for s in statuses
        )
        if settled and any(s == "error" for s in statuses):
            failed_ids.append(d.id)

    if limit and limit > 0:
        failed_ids = failed_ids[:limit]
    if not failed_ids:
        return {"status": "noop", "message": "No failed cases to retry", "count": 0}

    background_tasks.add_task(retry_failures, failed_ids)
    return {"status": "queued", "retrying": len(failed_ids), "job_ids": failed_ids}


@app.post("/api/sxs/resume", dependencies=[Depends(require_admin)])
async def sxs_resume(background_tasks: BackgroundTasks, stale_seconds: int = Query(120)):
    """Continue from where it stopped: reprocess every pair that is NOT fully
    done — failed pairs AND orphaned 'generating' pairs left by an interrupted
    run. Regenerates only the missing model(s) per pair, then re-evaluates.
    `stale_seconds` avoids touching a pair that is actively generating right now."""
    from google.cloud import firestore as _fs
    from sxs_pipeline import retry_failures
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))

    cutoff = time.time() - stale_seconds
    ids = []
    for d in db.collection(SXS_COLLECTION).where("source", "==", "sxs_auto").stream():
        j = d.to_dict()
        if _job_status(j) == "done":
            continue
        # Skip pairs that look like they're mid-flight right now.
        if _job_status(j) == "in_progress" and j.get("timestamp", 0) > cutoff:
            continue
        ids.append(d.id)

    if not ids:
        return {"status": "noop", "message": "Nothing incomplete to resume", "count": 0}
    background_tasks.add_task(retry_failures, ids)
    return {"status": "queued", "resuming": len(ids), "job_ids": ids}


@app.post("/api/sxs/director-eval", dependencies=[Depends(require_admin)])
async def sxs_director_eval(background_tasks: BackgroundTasks, force: bool = Query(False), limit: Optional[int] = Query(None)):
    """Run the pairwise Creative-Director critique on completed pairs (both
    models succeeded). By default only pairs missing `director_eval` are run."""
    from google.cloud import firestore as _fs
    from sxs_pipeline import director_backfill
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
    ids = []
    for d in db.collection(SXS_COLLECTION).where("source", "==", "sxs_auto").stream():
        j = d.to_dict()
        results = j.get("results") or {}
        succ = [k for k, r in results.items() if isinstance(r, dict) and r.get("status") == "success"]
        has_seed = any("seedance" in k for k in succ)
        has_omni = any("omni" in k for k in succ)
        if has_seed and has_omni and (force or not j.get("director_eval")):
            ids.append(d.id)
    if limit and limit > 0:
        ids = ids[:limit]
    if not ids:
        return {"status": "noop", "message": "No pairs need director eval", "count": 0}
    background_tasks.add_task(director_backfill, ids)
    return {"status": "queued", "count": len(ids), "job_ids": ids}


@app.post("/api/sxs/cleanup-orphans", dependencies=[Depends(require_admin)])
async def sxs_cleanup_orphans(older_than_seconds: int = Query(120)):
    """Delete SxS jobs that never completed (auto_eval_status != 'done') and are
    older than the cutoff — e.g. jobs orphaned by a server restart."""
    from google.cloud import firestore as _fs
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
    cutoff = time.time() - older_than_seconds
    deleted = []
    for d in db.collection(SXS_COLLECTION).where("source", "==", "sxs_auto").stream():
        j = d.to_dict()
        if j.get("auto_eval_status") != "done" and (j.get("timestamp", 0) < cutoff):
            db.collection(SXS_COLLECTION).document(d.id).delete()
            deleted.append(d.id)
    return {"status": "ok", "deleted_count": len(deleted), "deleted": deleted}


@app.get("/api/sxs/runs")
async def sxs_runs():
    """Run log: every batch launched + a summary of cases already done /
    in-progress, so the user can avoid duplicate (expensive) runs."""
    from google.cloud import firestore as _fs
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
    runs = [d.to_dict() for d in db.collection(SXS_RUNS_COLLECTION).stream()]
    runs.sort(key=lambda r: r.get("timestamp", 0), reverse=True)
    status_by_key = _already_run_keys(db)
    done = sum(1 for v in status_by_key.values() if v == "done")
    in_progress = sum(1 for v in status_by_key.values() if v == "in_progress")
    failed = sum(1 for v in status_by_key.values() if v == "failed")
    return {
        "runs": runs,
        "summary": {
            "total_runs": len(runs),
            "cases_done": done,
            "cases_failed": failed,
            "cases_in_progress": in_progress,
            "cases_touched": len(status_by_key),
        },
    }


@app.get("/api/sxs/failures")
async def sxs_failures():
    """List cases where either API (Seedance or Omni) did not produce a result,
    with the per-model error so they can be retried."""
    from google.cloud import firestore as _fs
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
    out = []
    for d in db.collection(SXS_COLLECTION).where("source", "==", "sxs_auto").stream():
        j = d.to_dict()
        results = j.get("results") or {}
        failed_models = [
            {"model_key": k, "status": r.get("status"), "error": r.get("error", "")}
            for k, r in results.items()
            if not (isinstance(r, dict) and r.get("status") == "success")
        ]
        # Only report once generation has settled (not still generating).
        statuses = [r.get("status") for r in results.values() if isinstance(r, dict)]
        settled = j.get("auto_eval_status") in ("done", "error") or all(
            s in ("success", "error") for s in statuses
        )
        if failed_models and settled:
            out.append({
                "job_id": d.id,
                "batch_id": j.get("batch_id"),
                "customer": j.get("customer"),
                "case_id": j.get("prompt_id"),
                "modality": j.get("modality"),
                "failed_models": failed_models,
            })
    out.sort(key=lambda x: (x.get("customer") or "", x.get("case_id") or ""))
    return {"count": len(out), "failures": out}


class SxsGcsRunRequest(BaseModel):
    cases_uri: str
    customers: Optional[List[str]] = None
    modalities: Optional[List[str]] = None
    limit: Optional[int] = None
    randomize: Optional[bool] = False
    skip_existing: Optional[bool] = True  # don't re-generate cases already run


@app.post("/api/sxs/run-gcs", dependencies=[Depends(require_admin)])
async def sxs_run_gcs(req: SxsGcsRunRequest, background_tasks: BackgroundTasks):
    """Load cases directly from a GCS JSON (references already gs:// URLs),
    optionally filter by customer/modality and cap with limit, then create one
    job per case and schedule Seedance+Omni generation + Core-5 auto-eval."""
    from sxs_pipeline import create_sxs_job, process_batch

    if not (req.cases_uri.startswith("gs://") or req.cases_uri.startswith("https://")):
        raise HTTPException(status_code=400, detail="cases_uri must be a gs:// or https:// URL")
    # Cap batch size — generation is expensive (Omni QPM + Gemini eval cost).
    MAX_BATCH = 100
    if req.limit is not None and req.limit > MAX_BATCH:
        req.limit = MAX_BATCH

    try:
        cases = _load_cases_from_gcs(req.cases_uri)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to load cases: {e}")

    from google.cloud import firestore as _fs
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))

    cust = {c.lower() for c in (req.customers or [])}
    mods = {m.lower() for m in (req.modalities or [])}
    selected = []
    for c in cases:
        if cust and (c.get("customer") or "").lower() not in cust:
            continue
        if mods and (c.get("modality") or c.get("mode") or "").lower() not in mods:
            continue
        selected.append(c)

    # Dedup guard: skip cases already generated/in-progress (generation is
    # expensive). Fully-errored cases remain re-runnable.
    skipped_existing = 0
    if req.skip_existing:
        already = _already_run_keys(db)
        fresh = [c for c in selected if already.get(_case_key(c)) != "done"]
        skipped_existing = len(selected) - len(fresh)
        selected = fresh

    if req.randomize:
        # Stratified random sampling across modality "categories" for variety:
        # round-robin pick from shuffled per-modality buckets up to `limit`.
        buckets: Dict[str, list] = {}
        for c in selected:
            key = (c.get("modality") or c.get("mode") or "?").upper()
            buckets.setdefault(key, []).append(c)
        for b in buckets.values():
            random.shuffle(b)
        order = list(buckets.keys())
        random.shuffle(order)
        target = req.limit if (req.limit and req.limit > 0) else len(selected)
        picked = []
        while len(picked) < target:
            active = [k for k in order if buckets[k]]
            if not active:
                break
            for k in active:
                if len(picked) >= target:
                    break
                picked.append(buckets[k].pop())
        selected = picked
    elif req.limit and req.limit > 0:
        selected = selected[: req.limit]
    if not selected:
        if skipped_existing:
            return {
                "status": "noop",
                "message": f"All {skipped_existing} matching case(s) were already run — nothing new to generate.",
                "skipped_existing": skipped_existing,
                "count": 0,
            }
        raise HTTPException(status_code=400, detail="No cases matched the filters")

    batch_id = f"batch_{int(time.time())}"
    pairs = [(create_sxs_job(c, batch_id=batch_id), c) for c in selected]
    background_tasks.add_task(process_batch, pairs)

    # Persist a run-log entry so the user can see what's been launched and avoid
    # duplicate (expensive) runs.
    db.collection(SXS_RUNS_COLLECTION).document(batch_id).set({
        "batch_id": batch_id,
        "timestamp": time.time(),
        "cases_uri": req.cases_uri,
        "filters": {
            "customers": req.customers or [],
            "modalities": req.modalities or [],
            "randomize": bool(req.randomize),
            "limit": req.limit,
        },
        "launched_count": len(pairs),
        "skipped_existing": skipped_existing,
        "job_ids": [jid for jid, _ in pairs],
        "case_keys": [_case_key(c) for _, c in pairs],
    })

    return {
        "status": "queued",
        "batch_id": batch_id,
        "job_ids": [jid for jid, _ in pairs],
        "count": len(pairs),
        "skipped_existing": skipped_existing,
    }


@app.post("/api/admin/generate-json", dependencies=[Depends(require_admin)])
async def admin_generate_json(
    background_tasks: BackgroundTasks,
    cases: UploadFile = File(...),
    files: List[UploadFile] = File(default=[]),
    skip_existing: bool = Query(True),
):
    """Admin: upload a cases JSON (+ optional asset files) and generate each case
    on ALL active registry models whose `type` matches the case modality, then
    run the Core-5 auto-eval. Stored in sxs_jobs (source=='sxs_auto')."""
    from util.asset_intake import (
        save_uploads_to_temp,
        upload_assets_to_gcs,
        rewrite_case_assets,
    )
    from sxs_pipeline import case_model_type, create_admin_job, process_admin_batch

    try:
        raw = await cases.read()
        parsed = json.loads(raw.decode("utf-8"))
        case_list = parsed.get("cases", parsed) if isinstance(parsed, dict) else parsed
        if not isinstance(case_list, list) or not case_list:
            raise ValueError("cases JSON must be a non-empty array of case objects")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid cases JSON: {e}")

    batch_id = f"batch_{int(time.time())}"

    # Stage uploaded asset files and push them to GCS, then rewrite relative paths.
    uploaded = []
    for f in files or []:
        data = await f.read()
        uploaded.append(type("U", (), {"filename": f.filename, "bytes": data})())
    relpath_to_url = {}
    if uploaded:
        base_dir = save_uploads_to_temp(uploaded)
        relpath_to_url = upload_assets_to_gcs(base_dir, batch_id)

    from google.cloud import firestore as _fs
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))

    already = _already_run_keys(db) if skip_existing else {}

    pairs = []
    skipped_existing = 0
    skipped_no_model = 0
    per_case_models = {}
    for case in case_list:
        rewritten = rewrite_case_assets(case, relpath_to_url) if relpath_to_url else case
        if skip_existing and already.get(_case_key(rewritten)) == "done":
            skipped_existing += 1
            continue
        mtype = case_model_type(rewritten)
        models = [
            {"id": m.id, "provider": m.provider, "model_id": m.model_id, "type": m.type}
            for m in registry.get_active_models() if m.type == mtype
        ]
        if not models:
            skipped_no_model += 1
            continue
        job_id = create_admin_job(rewritten, batch_id, models)
        pairs.append((job_id, rewritten, models))
        per_case_models[job_id] = [m["id"] for m in models]

    if pairs:
        background_tasks.add_task(process_admin_batch, pairs)
    jobs_manager.invalidate_cache()

    # Run-log entry so the user can see what's been launched.
    db.collection(SXS_RUNS_COLLECTION).document(batch_id).set({
        "batch_id": batch_id,
        "timestamp": time.time(),
        "filters": {"origin": "admin"},
        "launched_count": len(pairs),
        "skipped_existing": skipped_existing,
        "skipped_no_model": skipped_no_model,
        "job_ids": [jid for jid, _, _ in pairs],
        "case_keys": [_case_key(c) for _, c, _ in pairs],
    })

    return {
        "status": "queued",
        "batch_id": batch_id,
        "count": len(pairs),
        "job_ids": [jid for jid, _, _ in pairs],
        "skipped_existing": skipped_existing,
        "skipped_no_model": skipped_no_model,
        "per_case_models": per_case_models,
    }


class SxsComposeRequest(BaseModel):
    """A single composed video case from the admin compose-box form."""
    id: Optional[str] = None
    customer: Optional[str] = None
    prompt: str
    modality: Optional[str] = "t2v"
    reference_images: Optional[List[str]] = None
    reference_videos: Optional[List[str]] = None
    aspect_ratio: Optional[str] = "16:9"
    duration: Optional[int] = 8


@app.post("/api/sxs/compose", dependencies=[Depends(require_admin)])
async def sxs_compose(req: SxsComposeRequest, background_tasks: BackgroundTasks):
    """Run a single composed video case (from the compose-box form) on the
    active models matching its modality, then auto-eval."""
    from sxs_pipeline import case_model_type, create_admin_job, process_admin_batch
    case = req.dict()
    if not case.get("id"):
        case["id"] = f"compose_{int(time.time())}"
    case["reference_images"] = [u for u in (case.get("reference_images") or []) if u]
    case["reference_videos"] = [u for u in (case.get("reference_videos") or []) if u]
    mtype = case_model_type(case)
    models = [
        {"id": m.id, "provider": m.provider, "model_id": m.model_id, "type": m.type}
        for m in registry.get_active_models() if m.type == mtype
    ]
    if not models:
        raise HTTPException(status_code=400, detail=f"No active models for modality '{mtype}'")
    batch_id = f"batch_{int(time.time())}"
    job_id = create_admin_job(case, batch_id, models)
    background_tasks.add_task(process_admin_batch, [(job_id, case, models)])
    return {"status": "queued", "batch_id": batch_id, "job_ids": [job_id], "count": 1,
            "models": [m["id"] for m in models]}


class TranslateRequest(BaseModel):
    text: str


@app.post("/api/sxs/translate")
async def sxs_translate(req: TranslateRequest):
    """Translate a prompt (any language) to English with Gemini 2.5 Flash."""
    try:
        translation = await translate_to_english(req.text)
        return {"status": "success", "translation": translation}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/sxs/vote")
async def sxs_vote(req: SxsVoteRequest):
    """Store a human vote for an SxS pair in the isolated sxs_votes collection.

    Idempotency guard: ignore a duplicate vote from the same evaluator on the
    same pair within a short window (rapid double-clicks / retries)."""
    from google.cloud import firestore as _fs
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))

    now = time.time()
    dupe_window = 20  # seconds
    for v in (
        db.collection(SXS_VOTES_COLLECTION)
        .where("job_id", "==", req.job_id)
        .where("ldap", "==", req.ldap or "anonymous")
        .stream()
    ):
        d = v.to_dict()
        if (now - (d.get("timestamp") or 0)) < dupe_window:
            return {"status": "duplicate_ignored", "vote_id": d.get("id")}

    vote_id = f"sxsvote_{int(time.time()*1000)}"
    db.collection(SXS_VOTES_COLLECTION).document(vote_id).set({
        "id": vote_id,
        "job_id": req.job_id,
        "winner_side": req.winner_side,
        "winner_model": req.winner_model,
        "loser_model": req.loser_model,
        "scores": req.scores,
        "justification": req.justification,
        "ldap": req.ldap,
        "timestamp": time.time(),
    })
    return {"status": "success", "vote_id": vote_id}


# ===================================================================
# Tags
# ===================================================================
@app.post("/api/admin/generate-tags", dependencies=[Depends(require_admin)])
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


@app.post("/api/admin/backfill-tags", dependencies=[Depends(require_admin)])
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


@app.post("/api/admin/batch/sheet/load", dependencies=[Depends(require_admin)])
async def load_batch_sheet(req: SheetLoadRequest):
    try:
        data = read_sheet(req.url)
        return {"status": "success", "rows": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/admin/batch/sheet/update", dependencies=[Depends(require_admin)])
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


@app.delete("/api/admin/jobs/{job_id}", dependencies=[Depends(require_admin)])
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


@app.post("/api/admin/jobs/{job_id}/retry", dependencies=[Depends(require_admin)])
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
    omni_project: Optional[str] = None  # 'vital-octagon-19612' or 'cloud-llm-preview1'

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
            elif model.provider == "omni":
                img_to_pass = request.start_image_url or request.reference_image_url
                if not img_to_pass and request.reference_images:
                    img_to_pass = request.reference_images[0]
                tasks.append(generate_with_omni(
                    request.text, request.ratio, img_to_pass, model.model_id,
                    request.reference_images, mode=model.type,
                    project_override=request.omni_project,
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
            generation_history = current.get("generation_history", {})

            for k, v in response_results.items():
                # Archive previous successful result before overwriting
                if k in existing_results and existing_results[k].get("status") == "success":
                    prev = existing_results[k]
                    if k not in generation_history:
                        generation_history[k] = []
                    generation_history[k].append({
                        **prev,
                        "archived_at": time.time(),
                    })
                    print(f"Archived previous result for {k} (version {len(generation_history[k])})")
                existing_results[k] = v

            update_data = {"results": existing_results}
            if generation_history:
                update_data["generation_history"] = generation_history
            doc_ref.update(update_data)
            jobs_manager.invalidate_cache()
            print(f"Background Job {job_id} completed. Updated {len(response_results)} model(s).")

            # Regenerate HTML slideware with latest results
            batch_name = current.get("prompt_id") or job_id
            try:
                from generate_slideware import generate_for_batch
                generate_for_batch(batch_name)
            except Exception as slideware_err:
                print(f"Slideware generation failed for {batch_name}: {slideware_err}")
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


@app.post("/api/generate", dependencies=[Depends(require_admin)])
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


@app.post("/api/admin/votes/prune", dependencies=[Depends(require_admin)])
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


@app.get("/api/sxs/stats")
async def sxs_stats(ldap: Optional[str] = Query(None)):
    """Win rates / leaderboard for the isolated SxS test DB (sxs_votes + sxs_jobs).
    Scores use the Core-5 1-5 rubric (no default-skip)."""
    from google.cloud import firestore as _fs
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
    jobs = {
        d.id: d.to_dict()
        for d in db.collection(SXS_COLLECTION).where("source", "==", "sxs_auto").stream()
    }
    votes = [d.to_dict() for d in db.collection(SXS_VOTES_COLLECTION).stream()]

    def _mode_of(job):
        if not job:
            return "T2V"
        mod = (job.get("modality") or "").upper()
        if "R2V" in mod or "REF" in mod or "V2V" in mod or job.get("reference_videos"):
            return "R2V"
        if "I2V" in mod or job.get("reference_images"):
            return "I2V"
        return "T2V"

    def _compute(v_list):
        skus = {}
        modes = {"T2V": 0, "I2V": 0, "R2V": 0}
        model_lat = {}
        for job in jobs.values():
            for mid, res in (job.get("results") or {}).items():
                if isinstance(res, dict) and res.get("status") == "success" and "latency" in res:
                    model_lat.setdefault(mid, {"sum": 0, "count": 0})
                    model_lat[mid]["sum"] += res["latency"]
                    model_lat[mid]["count"] += 1

        for vote in v_list:
            job = jobs.get(vote.get("job_id"))
            mode = _mode_of(job)
            modes[mode] += 1
            wm, lm = vote.get("winner_model"), vote.get("loser_model")
            is_tie = (vote.get("winner_side") or "").strip().lower() == "tie"
            for mid in (wm, lm):
                if mid and mid not in skus:
                    skus[mid] = {
                        "global": {"wins": 0, "total": 0},
                        "T2V": {"wins": 0, "total": 0, "scores": []},
                        "I2V": {"wins": 0, "total": 0, "scores": []},
                        "R2V": {"wins": 0, "total": 0, "scores": []},
                    }
            if is_tie:
                # Tie: both models are credited a win (each gets a vote).
                for mid in (wm, lm):
                    if not mid:
                        continue
                    skus[mid]["global"]["wins"] += 1
                    skus[mid]["global"]["total"] += 1
                    skus[mid][mode]["wins"] += 1
                    skus[mid][mode]["total"] += 1
                    if vote.get("scores"):
                        skus[mid][mode]["scores"].append(vote["scores"])
            else:
                if wm:
                    skus[wm]["global"]["wins"] += 1
                    skus[wm]["global"]["total"] += 1
                    skus[wm][mode]["wins"] += 1
                    skus[wm][mode]["total"] += 1
                    if vote.get("scores"):
                        skus[wm][mode]["scores"].append(vote["scores"])
                if lm:
                    skus[lm]["global"]["total"] += 1
                    skus[lm][mode]["total"] += 1

        def avg_scores(score_list):
            if not score_list:
                return {}
            sums, counts = {}, {}
            for s in score_list:
                for k, v in s.items():
                    # 3 is the slider default on the 1-5 scale → treat as "not
                    # actively rated" and exclude from averages / spider chart.
                    if v == 3:
                        continue
                    sums[k] = sums.get(k, 0) + v
                    counts[k] = counts.get(k, 0) + 1
            return {k: round(sums[k] / counts[k], 2) for k in sums if counts.get(k)}

        leaderboard = []
        for mid, data in skus.items():
            g = data["global"]
            gr = (g["wins"] / g["total"]) * 100 if g["total"] else 0
            lps = round(model_lat[mid]["sum"] / model_lat[mid]["count"], 2) if mid in model_lat and model_lat[mid]["count"] else 0
            entry = {"model_id": mid, "win_rate": round(gr, 1), "wins": g["wins"], "total": g["total"], "latency_ps": lps}
            for m in ("T2V", "I2V", "R2V"):
                mk = m.lower()
                d = data[m]
                r = (d["wins"] / d["total"]) * 100 if d["total"] else 0
                entry[f"{mk}_rate"] = round(r, 1)
                entry[f"{mk}_total"] = d["total"]
                entry[f"{mk}_wins"] = d["wins"]
                entry[f"{mk}_scores"] = avg_scores(d["scores"])
            leaderboard.append(entry)

        return {
            "total_evals": len(v_list),
            "modes": modes,
            "skus": sorted(leaderboard, key=lambda x: x["win_rate"], reverse=True),
        }

    result = {"global": _compute(votes)}
    if ldap:
        result["user"] = _compute([v for v in votes if v.get("ldap", "anonymous") == ldap])
    return result


@app.get("/api/sxs/leaderboard/users")
async def sxs_user_leaderboard():
    from google.cloud import firestore as _fs
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
    counts = Counter()
    for d in db.collection(SXS_VOTES_COLLECTION).stream():
        v = d.to_dict()
        ld = v.get("ldap", "")
        if ld and ld != "anonymous":
            counts[ld] += 1
    top_10 = sorted([{"ldap": k, "count": v} for k, v in counts.items()], key=lambda x: x["count"], reverse=True)[:10]
    return {"status": "success", "leaderboard": top_10}


@app.get("/api/analytics/latency")
async def analytics_latency():
    """Average generation latency per (modality, model) across all modalities:
    video (t2v/i2v/r2v from sxs_jobs), image (t2i/i2i from image_jobs), and
    speech (tts from tts_jobs). Latency normalized to SECONDS (video stores
    `latency` in s; image/tts store `latency_ms`)."""
    from google.cloud import firestore as _fs
    from sxs_pipeline import modality_to_type
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))

    # acc[(modality, model)] = [sum_seconds, count]
    acc: Dict[tuple, list] = {}

    def add(modality: str, model: str, seconds: float):
        if seconds is None or model is None:
            return
        key = (modality, model)
        a = acc.setdefault(key, [0.0, 0])
        a[0] += float(seconds)
        a[1] += 1

    # --- Video: sxs_jobs (latency in seconds; model = result key) ---
    sxs_coll = os.getenv("SXS_COLLECTION", "sxs_jobs")
    for d in db.collection(sxs_coll).where("source", "==", "sxs_auto").stream():
        j = d.to_dict()
        modality = modality_to_type(j.get("modality") or "t2v")  # -> t2v/i2v/r2v
        for mid, r in (j.get("results") or {}).items():
            if isinstance(r, dict) and r.get("status") == "success" and r.get("latency") is not None:
                add(modality, mid, r.get("latency"))

    # --- Image: image_jobs (latency_ms; model = result.engine; modality = mode t2i/i2i) ---
    img_coll = os.getenv("IMAGE_COLLECTION", "image_jobs")
    try:
        for d in db.collection(img_coll).stream():
            j = d.to_dict()
            modality = (j.get("mode") or "t2i").lower()
            for r in (j.get("results") or {}).values():
                if isinstance(r, dict) and r.get("status") == "success" and r.get("latency_ms") is not None:
                    add(modality, r.get("engine") or r.get("model"), r.get("latency_ms") / 1000.0)
    except Exception as e:
        print(f"[analytics_latency] image scan failed: {e}")

    # --- Speech: tts_jobs (latency_ms; model = result.engine; modality = 'tts') ---
    tts_coll = os.getenv("TTS_COLLECTION", "tts_jobs")
    try:
        for d in db.collection(tts_coll).stream():
            j = d.to_dict()
            for r in (j.get("results") or {}).values():
                if isinstance(r, dict) and r.get("status") == "success" and r.get("latency_ms") is not None:
                    add("tts", r.get("engine") or r.get("model"), r.get("latency_ms") / 1000.0)
    except Exception as e:
        print(f"[analytics_latency] tts scan failed: {e}")

    rows = [
        {
            "modality": mod,
            "model": model,
            "avg_latency_s": round(s / n, 2) if n else None,
            "samples": n,
        }
        for (mod, model), (s, n) in acc.items()
    ]
    order = {"t2v": 0, "i2v": 1, "r2v": 2, "t2i": 3, "i2i": 4, "tts": 5}
    rows.sort(key=lambda x: (order.get(x["modality"], 9), -x["samples"]))
    return {"rows": rows, "modalities": ["t2v", "i2v", "r2v", "t2i", "i2i", "tts"]}


# ===================================================================
# Health & Media Proxy
# ===================================================================
@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "service": "Project Pulse Backend"}


@app.get("/api/media")
async def get_media_proxy(url: str = Query(...), request: Request = None):
    from util.gcs_utils import https_to_gs, get_upload_client
    import urllib.parse

    try:
        # Fix malformed gs:/ URLs (single slash instead of double)
        fixed_url = url
        if fixed_url.startswith("gs:/") and not fixed_url.startswith("gs://"):
            fixed_url = "gs://" + fixed_url[4:]

        gs_uri = https_to_gs(fixed_url)
        # SSRF guard: only proxy Google Cloud Storage objects (gs:// or the
        # GCS HTTPS host). Reject arbitrary hosts so this endpoint can't be
        # used as an open proxy.
        if not gs_uri.startswith("gs://"):
            raise HTTPException(status_code=400, detail="Only GCS URLs are allowed")

        parts = gs_uri.replace("gs://", "").split("/")
        bucket_name = parts[0]
        blob_name = "/".join(parts[1:])

        client = get_upload_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        blob.reload()  # get metadata (size)

        total_size = blob.size
        ct = "image/jpeg"
        url_lower = url.lower()
        if ".png" in url_lower:
            ct = "image/png"
        elif ".mp4" in url_lower:
            ct = "video/mp4"
        elif ".html" in url_lower:
            ct = "text/html"

        # Handle Range requests for video seeking
        range_header = request.headers.get("range") if request else None
        if range_header and total_size:
            range_match = range_header.replace("bytes=", "").split("-")
            start = int(range_match[0]) if range_match[0] else 0
            end = int(range_match[1]) if len(range_match) > 1 and range_match[1] else total_size - 1
            end = min(end, total_size - 1)
            length = end - start + 1

            # GCS download_as_bytes end param is exclusive
            data = blob.download_as_bytes(start=start, end=end + 1)
            return Response(
                content=data,
                status_code=206,
                media_type=ct,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{total_size}",
                    "Content-Length": str(len(data)),
                    "Accept-Ranges": "bytes",
                    "Cache-Control": "public, max-age=3600",
                },
            )

        # Stream full file in chunks
        def stream_blob():
            with blob.open("rb") as f:
                while True:
                    chunk = f.read(2 * 1024 * 1024)  # 2MB chunks
                    if not chunk:
                        break
                    yield chunk

        return StreamingResponse(
            stream_blob(),
            media_type=ct,
            headers={
                "Content-Length": str(total_size) if total_size else "",
                "Accept-Ranges": "bytes",
                "Cache-Control": "public, max-age=3600",
            },
        )
    except HTTPException:
        raise  # preserve SSRF-guard 400 and other explicit statuses
    except Exception as e:
        print(f"Error proxying media {url}: {e}")
        raise HTTPException(status_code=404, detail="Failed to load media")


# ===================================================================
# Google Slides generation
# ===================================================================
@app.post("/api/slides/generate", dependencies=[Depends(require_admin)])
async def generate_slides(
    batches: List[str] = Query(default=[]),
    force_new: bool = Query(default=False),
    background_tasks: BackgroundTasks = None,
):
    """Generate Google Slides presentation with Drive-embedded videos.
    - batches: list of batch names to include (empty = all)
    - force_new: create a fresh presentation instead of appending
    """
    from generate_google_slides import create_presentation
    batch_filter = batches if batches else None
    try:
        url = create_presentation(batch_filter=batch_filter, force_new=force_new)
        return {"status": "ok", "url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/slides/append/{batch_name}", dependencies=[Depends(require_admin)])
async def append_slides_for_batch(batch_name: str):
    """Append a single batch to the existing Google Slides presentation."""
    from generate_google_slides import append_batch_slides
    try:
        url = append_batch_slides(batch_name)
        if url:
            return {"status": "ok", "url": url}
        return {"status": "skipped", "message": f"{batch_name} already in presentation or no data"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===================================================================
# Slideware (HTML)
# ===================================================================
@app.get("/slideware")
async def serve_slideware():
    """Serve the generated HTML slideware presentation."""
    path = os.path.join(os.path.dirname(__file__), "slideware.html")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Slideware not generated yet. Run a generation first.")
    with open(path) as f:
        return HTMLResponse(content=f.read())


@app.post("/api/slideware/regenerate", dependencies=[Depends(require_admin)])
async def regenerate_slideware():
    """Regenerate the slideware HTML from current Firestore data."""
    from generate_slideware import fetch_jobs, generate_presentation
    jobs = fetch_jobs()
    result = generate_presentation(jobs, output_path=os.path.join(os.path.dirname(__file__), "slideware.html"))
    if result:
        return {"status": "ok", "message": f"Generated slideware"}
    raise HTTPException(status_code=500, detail="No slides generated — no successful videos found")


@app.post("/api/slideware/pptx", dependencies=[Depends(require_admin)])
async def generate_pptx_endpoint(batches: List[str] = Query(default=[])):
    """Generate and download a PPTX with embedded videos for specified batches."""
    from generate_pptx import generate_pptx
    out_path = os.path.join(os.path.dirname(__file__), "project_pulse_export.pptx")
    batch_filter = batches if batches else None
    result = generate_pptx(batch_filter=batch_filter, output_path=out_path)
    if not result:
        raise HTTPException(status_code=500, detail="No slides generated")
    with open(out_path, "rb") as f:
        data = f.read()
    filename = "Project_Pulse.pptx"
    if batch_filter:
        filename = f"Project_Pulse_{'_'.join(batch_filter)}.pptx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/slideware/pptx/download")
async def download_existing_pptx():
    """Download the most recently generated PPTX."""
    for name in ["project_pulse_test.pptx", "project_pulse_export.pptx"]:
        path = os.path.join(os.path.dirname(__file__), name)
        if os.path.exists(path):
            with open(path, "rb") as f:
                data = f.read()
            return Response(
                content=data,
                media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                headers={"Content-Disposition": f'attachment; filename="{name}"'},
            )
    raise HTTPException(status_code=404, detail="No PPTX file found. Generate one first via POST /api/slideware/pptx")


# ===================================================================
# Slideware feedback (best video picks + comments)
# ===================================================================
class SlideFeedback(BaseModel):
    batch_name: str
    model_key: Optional[str] = None
    tier: str  # "pro" or "fast"
    user_name: Optional[str] = None
    comment: Optional[str] = None


@app.get("/api/slideware/feedback")
async def get_slideware_feedback():
    """Get all feedback (best picks + comments) for slideware."""
    from google.cloud import firestore as _fs
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
    docs = db.collection("slideware_feedback").stream()
    feedback = {}
    for doc in docs:
        feedback[doc.id] = doc.to_dict()
    return feedback


@app.post("/api/slideware/feedback/pick", dependencies=[Depends(require_admin)])
async def set_best_video(body: SlideFeedback):
    """Set the best video pick for a batch+tier."""
    from google.cloud import firestore as _fs
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
    doc_id = f"{body.batch_name}__{body.tier}"
    db.collection("slideware_feedback").document(doc_id).set({
        "batch_name": body.batch_name,
        "tier": body.tier,
        "best_model": body.model_key,
        "picked_by": body.user_name or "anonymous",
    }, merge=True)
    return {"status": "ok"}


@app.post("/api/slideware/feedback/comment", dependencies=[Depends(require_admin)])
async def add_comment(body: SlideFeedback):
    """Add a comment to a batch+tier."""
    from google.cloud import firestore as _fs
    import datetime
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
    doc_id = f"{body.batch_name}__{body.tier}"
    doc_ref = db.collection("slideware_feedback").document(doc_id)
    doc = doc_ref.get()
    existing = doc.to_dict() if doc.exists else {}
    comments = existing.get("comments", [])
    comments.append({
        "text": body.comment,
        "user": body.user_name or "anonymous",
        "timestamp": datetime.datetime.now().isoformat(),
    })
    doc_ref.set({
        "batch_name": body.batch_name,
        "tier": body.tier,
        "comments": comments,
    }, merge=True)
    return {"status": "ok", "comments": comments}


# ===================================================================
# Cross-modality vote count — gates Analytics access (10-vote unlock)
# ===================================================================
@app.get("/api/votes/count")
async def votes_count(ldap: str = Query("")):
    """Total votes a user (by ldap) has cast across ALL modalities
    (video sxs_votes + image_votes + tts_votes + legacy votes). Used by the
    Analytics page to enforce the 10-vote access gate."""
    required = 10
    ldap = (ldap or "").strip()
    if not ldap or ldap.lower() in ("global", "anonymous"):
        return {"ldap": ldap, "count": 0, "required": required, "unlocked": False}
    from google.cloud import firestore as _fs
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
    total = 0
    for coll in (SXS_VOTES_COLLECTION, "image_votes", "tts_votes", "votes"):
        try:
            total += sum(1 for _ in db.collection(coll).where("ldap", "==", ldap).stream())
        except Exception:
            pass
    return {"ldap": ldap, "count": total, "required": required, "unlocked": total >= required}


@app.get("/api/votes/leaderboard")
async def votes_leaderboard():
    """Top evaluators across ALL modalities (video + image + tts + legacy)."""
    from collections import Counter
    from google.cloud import firestore as _fs
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
    counts: Counter = Counter()
    for coll in (SXS_VOTES_COLLECTION, "image_votes", "tts_votes", "votes"):
        try:
            for d in db.collection(coll).stream():
                ld = (d.to_dict() or {}).get("ldap")
                if ld and str(ld).lower() not in ("anonymous", "global"):
                    counts[str(ld)] += 1
        except Exception:
            pass
    leaderboard = [{"ldap": k, "count": v} for k, v in counts.most_common(50)]
    return {"status": "success", "leaderboard": leaderboard}


# ===================================================================
# Image & TTS SxS modalities (self-contained routers, isolated collections)
# Registered BEFORE the static catch-all mount so /api/* paths win.
# ===================================================================
from image_routes import router as image_router
from tts_routes import router as tts_router
app.include_router(image_router)
app.include_router(tts_router)


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
