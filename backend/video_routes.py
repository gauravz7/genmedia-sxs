"""Video SxS ("sxs") — JSON-driven generation, blind pairs, votes and
batch operations, all under /api/sxs/*.

The live video path. Its Firestore collections (`sxs_jobs`, `sxs_votes`,
`sxs_runs`) are isolated from the legacy `eval_jobs` flow, mirroring how
`image_routes` and `tts_routes` own their modalities."""

import json
import os
import random
import time
from typing import Dict, List, Optional

from fastapi import (APIRouter, BackgroundTasks, Depends, File, HTTPException,
                     Query, UploadFile)
from fastapi.responses import Response
from pydantic import BaseModel

from auth import require_admin
from config import (SXS_COLLECTION,
                    SXS_RUNS_COLLECTION, SXS_VOTES_COLLECTION, normalize_gcs_url)
from registry import registry
from providers.vertex_provider import translate_to_english
from store import jobs_manager
from util.gcs_utils import get_signed_url

router = APIRouter()


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


@router.post("/api/sxs/upload", dependencies=[Depends(require_admin)])
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


@router.get("/api/sxs/jobs")
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


@router.get("/api/sxs/jobs/{job_id}")
async def sxs_get_job(job_id: str):
    from google.cloud import firestore as _fs
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
    doc = db.collection(SXS_COLLECTION).document(job_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Job not found")
    d = doc.to_dict()
    d["id"] = doc.id
    return _sign_sxs_job(d)


@router.delete("/api/sxs/jobs/{job_id}", dependencies=[Depends(require_admin)])
async def sxs_delete_job(job_id: str):
    """Delete an SxS pair from the isolated sxs_jobs collection."""
    from google.cloud import firestore as _fs
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
    ref = db.collection(SXS_COLLECTION).document(job_id)
    if not ref.get().exists:
        raise HTTPException(status_code=404, detail="Job not found")
    ref.delete()
    return {"status": "deleted", "job_id": job_id}


@router.post("/api/sxs/jobs/{job_id}/retry", dependencies=[Depends(require_admin)])
async def sxs_retry_job(job_id: str, background_tasks: BackgroundTasks):
    """Re-generate the failed model(s) of one SxS pair, then re-run auto-eval."""
    from google.cloud import firestore as _fs
    from sxs_pipeline import retry_job
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
    if not db.collection(SXS_COLLECTION).document(job_id).get().exists:
        raise HTTPException(status_code=404, detail="Job not found")
    background_tasks.add_task(retry_job, job_id)
    return {"status": "retrying", "job_id": job_id}


@router.get("/api/sxs/aieval/{job_id}")
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


@router.get("/api/sxs/report.json")
async def sxs_report_json(batch: Optional[str] = Query(None)):
    data = await sxs_list_jobs(batch=batch)
    return data


@router.get("/api/sxs/report.csv")
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


@router.get("/api/sxs/pair")
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


@router.get("/api/sxs/catalog")
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


@router.post("/api/sxs/retry-failures", dependencies=[Depends(require_admin)])
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


@router.post("/api/sxs/resume", dependencies=[Depends(require_admin)])
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


@router.post("/api/sxs/director-eval", dependencies=[Depends(require_admin)])
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


@router.post("/api/sxs/cleanup-orphans", dependencies=[Depends(require_admin)])
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


@router.get("/api/sxs/runs")
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


@router.get("/api/sxs/failures")
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


@router.post("/api/sxs/run-gcs", dependencies=[Depends(require_admin)])
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


@router.post("/api/admin/generate-json", dependencies=[Depends(require_admin)])
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


@router.post("/api/sxs/compose", dependencies=[Depends(require_admin)])
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


@router.post("/api/sxs/translate")
async def sxs_translate(req: TranslateRequest):
    """Translate a prompt (any language) to English with Gemini 2.5 Flash."""
    try:
        translation = await translate_to_english(req.text)
        return {"status": "success", "translation": translation}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/sxs/vote")
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
