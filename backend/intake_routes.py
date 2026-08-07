"""Standard data-intake API (self-contained APIRouter).

Two ways for a customer's data to enter the platform, one pair of endpoints per
modality:

    POST /api/{sxs,image,tts}/prompts   "here are prompts — run them on these
                                         named models"
    POST /api/{sxs,image,tts}/outputs   "here are prompts AND the media I
                                         already generated — register them"

Either way the case ends up as a normal job doc and shows up in the blind duel
and the analytics. The difference is only whether we generate the media or the
customer supplies it.

Every named model is checked against the one shared registry
(`model_resolver.resolve_models`) — an unknown or deactivated name is a 400 that
lists what went wrong and what *is* available, rather than a job that silently
never produces media.

Wire it into main.py (before the static mount) with:

    from intake_routes import router as intake_router
    app.include_router(intake_router)

Does NOT import main.py at module level — `require_admin` is re-implemented
locally, following the `image_routes.py` / `tts_routes.py` convention.
"""

import hashlib
import hmac
import os
import time
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel

import model_resolver
from intake import IngestError, autotag_job, ingest_case, run_eval_for

load_dotenv()

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS")
_ADMIN_TOKEN_SALT = "project-pulse-sxs:v1"

# No prefix — full paths are spelled out in each decorator, as elsewhere.
router = APIRouter()


# ===================================================================
# Auth (local mirror of main.require_admin — same token)
# ===================================================================
def _admin_token() -> Optional[str]:
    if not ADMIN_PASS:
        return None
    return hashlib.sha256(
        f"{_ADMIN_TOKEN_SALT}:{ADMIN_USER}:{ADMIN_PASS}".encode()
    ).hexdigest()


async def require_admin(x_admin_token: str = Header(None)):
    expected = _admin_token()
    if not expected:
        raise HTTPException(status_code=500, detail="ADMIN_PASS not configured on server")
    if not x_admin_token or not hmac.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=401, detail="Admin authentication required")


# ===================================================================
# Request / response models
# ===================================================================
class PromptsRequest(BaseModel):
    """Generate: run every case on every named model."""
    models: List[str]
    cases: List[Dict[str, Any]]
    run_eval: bool = True
    batch_id: Optional[str] = None


class OutputsRequest(BaseModel):
    """Register: each case carries its own `outputs` manifest,
    `{model_id: "https://..."}` or `{model_id: {url, latency_ms, metadata}}`.

    The models are per-case rather than per-request because a customer's export
    is rarely uniform — one case may compare A vs B and the next B vs C.
    """
    cases: List[Dict[str, Any]]
    run_eval: bool = True
    batch_id: Optional[str] = None
    source_label: str = "api ingest"


def _batch_id(req, modality: str) -> str:
    return (req.batch_id or "").strip() or f"{modality}_intake_{int(time.time())}"


def _envelope(batch_id: str, job_ids: List[str], skipped: List[dict]) -> dict:
    """The one response shape all six endpoints return. A bad row is reported,
    it never aborts the batch — a 500-case upload with two malformed rows should
    still produce 498 jobs."""
    return {
        "status": "ok" if job_ids else "failed",
        "batch_id": batch_id,
        "job_ids": job_ids,
        "count": len(job_ids),
        "skipped": skipped,
    }


def _case_id(case: dict, index: int) -> str:
    return str(case.get("id") or f"(case #{index})")


def _require_cases(cases: List[dict]) -> None:
    if not cases:
        raise HTTPException(status_code=400, detail="No cases supplied.")


# ===================================================================
# Registry discovery — what can I ask for?
# ===================================================================
@router.get("/api/intake/models")
async def intake_models(modality: Optional[str] = None, active_only: bool = True):
    """The model names accepted by `models` / `outputs` keys, per modality.

    Unauthenticated on purpose: it is the same information `/api/models` already
    exposes, and a caller needs it to build a valid request.
    """
    if modality and modality not in ("video", "image", "tts"):
        raise HTTPException(
            status_code=400,
            detail=f"Unknown modality '{modality}'. Use video, image or tts.",
        )
    return {"models": model_resolver.list_models(modality, active_only=active_only)}


# ===================================================================
# /prompts — generate
# ===================================================================
@router.post("/api/sxs/prompts", dependencies=[Depends(require_admin)])
async def sxs_prompts(req: PromptsRequest, background: BackgroundTasks):
    """Run video cases on explicitly named models.

    Video duels are N-way, so any number of models may be named. Each must match
    the case's own type (t2v/i2v/r2v) — a t2v model on an i2v case would ignore
    the reference image and produce a duel that isn't comparing what it claims.
    """
    from sxs_pipeline import case_model_type, create_admin_job, process_admin_batch

    _require_cases(req.cases)
    specs = model_resolver.resolve_models("video", req.models)
    model_list = [s.model_dump() for s in specs]
    batch_id = _batch_id(req, "sxs")

    triples, job_ids, skipped = [], [], []
    for i, case in enumerate(req.cases):
        try:
            model_resolver.require_video_type(specs, case_model_type(case))
            job_id = create_admin_job(case, batch_id, model_list)
            if not req.run_eval:
                _mark_eval_skipped("video", job_id)
            triples.append((job_id, case, model_list))
            job_ids.append(job_id)
        except HTTPException as e:
            skipped.append({"index": i, "id": _case_id(case, i), "reason": _detail(e)})
        except Exception as e:
            skipped.append({"index": i, "id": _case_id(case, i), "reason": str(e)})

    if triples:
        background.add_task(process_admin_batch, triples)
    return _envelope(batch_id, job_ids, skipped)


@router.post("/api/image/prompts", dependencies=[Depends(require_admin)])
async def image_prompts(req: PromptsRequest, background: BackgroundTasks):
    """Run image cases on an explicitly named pair of models.

    Bypasses the preset MATCHUPS registry: `resolve_models` requires exactly 2
    models because the image job doc is two-sided (results keyed A/B).
    """
    from image_pipeline import create_image_job_with_sides, process_batch

    _require_cases(req.cases)
    specs = model_resolver.resolve_models("image", req.models)
    side_a, side_b = model_resolver.image_sides_from_specs(specs)
    batch_id = _batch_id(req, "image")

    pairs, job_ids, skipped = [], [], []
    for i, case in enumerate(req.cases):
        try:
            job_id = create_image_job_with_sides(
                case, side_a, side_b, batch_id=batch_id, run_eval=req.run_eval
            )
            pairs.append((job_id, case))
            job_ids.append(job_id)
        except Exception as e:
            skipped.append({"index": i, "id": _case_id(case, i), "reason": str(e)})

    if pairs:
        background.add_task(process_batch, pairs)
    return _envelope(batch_id, job_ids, skipped)


@router.post("/api/tts/prompts", dependencies=[Depends(require_admin)])
async def tts_prompts(req: PromptsRequest, background: BackgroundTasks):
    """Run TTS cases on an explicitly named pair of engines.

    Single- vs multi-speaker is a property of the CASE (`mode` + `speakers`),
    not of the engine, so both engines render whichever the case asks for.
    """
    from tts_pipeline import create_tts_job_with_engines, process_tts_batch

    _require_cases(req.cases)
    specs = model_resolver.resolve_models("tts", req.models)
    engines = model_resolver.tts_engines_from_specs(specs)
    batch_id = _batch_id(req, "tts")

    pairs, job_ids, skipped = [], [], []
    for i, case in enumerate(req.cases):
        try:
            job_id = create_tts_job_with_engines(
                case, engines, batch_id=batch_id, run_eval=req.run_eval
            )
            pairs.append((job_id, case))
            job_ids.append(job_id)
        except Exception as e:
            skipped.append({"index": i, "id": _case_id(case, i), "reason": str(e)})

    if pairs:
        background.add_task(process_tts_batch, pairs)
    return _envelope(batch_id, job_ids, skipped)


# ===================================================================
# /outputs — register customer-generated media
# ===================================================================
def _ingest_batch(modality: str, req: OutputsRequest, background: BackgroundTasks) -> dict:
    """Shared body of the three /outputs endpoints — the per-modality differences
    all live behind `intake.ingest_case`."""
    _require_cases(req.cases)
    batch_id = _batch_id(req, modality)

    job_ids, skipped = [], []
    for i, case in enumerate(req.cases):
        try:
            outputs = case.get("outputs") or case.get("results") or {}
            if not isinstance(outputs, dict) or not outputs:
                raise IngestError("case has no `outputs` object")
            specs = model_resolver.resolve_models(modality, list(outputs.keys()))
            job_id = ingest_case(
                modality, case, specs, batch_id=batch_id,
                run_eval=req.run_eval, source_label=req.source_label,
            )
            job_ids.append(job_id)
            # LLM-tag before judging. An ingested job never runs a generator, so
            # this is the only place it can pick up the categories that the
            # tag-filtered analytics and the arena tag filter key off. Each
            # modality reuses its own generated-path tagger; TTS is already
            # tagged inside `build_tts_job_doc` and so is a no-op here.
            background.add_task(autotag_job, modality, job_id, case)
            if req.run_eval:
                background.add_task(run_eval_for, modality, job_id)
        except HTTPException as e:
            skipped.append({"index": i, "id": _case_id(case, i), "reason": _detail(e)})
        except Exception as e:
            skipped.append({"index": i, "id": _case_id(case, i), "reason": str(e)})

    return _envelope(batch_id, job_ids, skipped)


@router.post("/api/sxs/outputs", dependencies=[Depends(require_admin)])
async def sxs_outputs(req: OutputsRequest, background: BackgroundTasks):
    """Register customer-generated VIDEO. N-way; `outputs` is keyed by model id."""
    return _ingest_batch("video", req, background)


@router.post("/api/image/outputs", dependencies=[Depends(require_admin)])
async def image_outputs(req: OutputsRequest, background: BackgroundTasks):
    """Register customer-generated IMAGES. Exactly 2 outputs per case."""
    return _ingest_batch("image", req, background)


@router.post("/api/tts/outputs", dependencies=[Depends(require_admin)])
async def tts_outputs(req: OutputsRequest, background: BackgroundTasks):
    """Register customer-generated AUDIO. Exactly 2 outputs per case."""
    return _ingest_batch("tts", req, background)


# ===================================================================
# Helpers
# ===================================================================
def _detail(e: HTTPException) -> str:
    """Flatten resolve_models' structured 400 into one skipped-row reason."""
    d = e.detail
    if isinstance(d, dict):
        problems = d.get("problems")
        if problems:
            return "; ".join(str(p) for p in problems)
        return str(d.get("error") or d)
    return str(d)


def _mark_eval_skipped(modality: str, job_id: str) -> None:
    """Video's `create_admin_job` has no run_eval parameter, so the flag is
    written onto the doc afterwards; `process_admin_job` checks it before
    judging."""
    from sxs_pipeline import EVAL_COLLECTION, _get_firestore_client
    _get_firestore_client().collection(EVAL_COLLECTION).document(job_id).update(
        {"auto_eval_status": "skipped"}
    )
