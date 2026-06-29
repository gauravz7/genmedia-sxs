"""Image SxS API routes (self-contained APIRouter).

Mirrors the video `/api/sxs/*` and TTS `/api/tts/*` endpoints, scoped to the
isolated `image_jobs` / `image_votes` Firestore collections, so the Image
modality cannot affect the video or TTS flows. Wire it into main.py with:

    from image_routes import router as image_router
    app.include_router(image_router)

Does NOT import main.py — `require_admin` and the admin-token derivation are
re-implemented locally (identical token: sha256("project-pulse-sxs:v1:" +
ADMIN_USER + ":" + ADMIN_PASS), sent as the X-Admin-Token header).

Endpoints use full `/api/image/...` paths (no APIRouter prefix), per the build
brief. Images are served through a LOCAL image-aware media proxy
(`/api/image/media`) that supports Range requests.
"""

import hashlib
import hmac
import io
import json
import os
import random
import time
import urllib.parse
from collections import Counter
from typing import Dict, List, Optional

from dotenv import load_dotenv
from fastapi import (
    APIRouter, BackgroundTasks, Depends, File, Header, HTTPException, Query,
    Request, Response, UploadFile,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

load_dotenv()

GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "vital-octagon-19612")
IMAGE_COLLECTION = os.getenv("IMAGE_COLLECTION", "image_jobs")
IMAGE_VOTES_COLLECTION = os.getenv("IMAGE_VOTES_COLLECTION", "image_votes")

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS")
_ADMIN_TOKEN_SALT = "project-pulse-sxs:v1"

# No prefix — full paths are spelled out in each decorator per the brief.
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
# Helpers
# ===================================================================
def _db():
    from google.cloud import firestore
    return firestore.Client(project=GCP_PROJECT_ID)


def _is_gcs(u: Optional[str]) -> bool:
    return bool(u) and (u.startswith("gs://") or "storage.googleapis.com" in u)


def _normalize(u: str) -> str:
    if not u:
        return u
    if "/api/image/media?url=" in u:
        return urllib.parse.unquote(u.split("/api/image/media?url=")[-1])
    if "X-Goog-Signature" in u or "?X-Goog-Algorithm" in u:
        return u.split("?")[0]
    return u


def _proxy(u: Optional[str]) -> Optional[str]:
    """Return a browser-loadable URL routed through the local image proxy."""
    if not u:
        return u
    if "/api/image/media?url=" in u:
        return u
    if _is_gcs(u):
        return f"/api/image/media?url={urllib.parse.quote(_normalize(u))}"
    return u


def _result_url(res: dict) -> Optional[str]:
    if not isinstance(res, dict):
        return None
    return res.get("url") or res.get("gcs_url") or (res.get("result") or {}).get("url")


def _sign_job(d: dict) -> dict:
    """Proxy the image URLs (results + input_image) of a job doc for the browser."""
    if d.get("input_image"):
        d["input_image"] = _proxy(d["input_image"])
    for _label, res in (d.get("results") or {}).items():
        if isinstance(res, dict):
            if res.get("url"):
                res["url"] = _proxy(res["url"])
            if isinstance(res.get("result"), dict) and res["result"].get("url"):
                res["result"]["url"] = _proxy(res["result"]["url"])
    return d


# ===================================================================
# Matchup registry (for the admin UI)
# ===================================================================
@router.get("/api/image/matchups")
async def image_matchups():
    from image_pipeline import list_matchups, DEFAULT_MATCHUP
    return {"matchups": list_matchups(), "default": DEFAULT_MATCHUP}


# ===================================================================
# Upload / run
# ===================================================================
@router.post("/api/image/upload", dependencies=[Depends(require_admin)])
async def image_upload(
    background_tasks: BackgroundTasks,
    cases: UploadFile = File(...),
    files: List[UploadFile] = File(default=[]),
):
    """Upload an image cases JSON + (optional) local input-image files; create one
    job per case and schedule background two-model generation + AI judge.

    Relative `input_image` paths in the cases JSON are resolved to GCS URLs from
    the uploaded files (reusing util.asset_intake)."""
    from util.asset_intake import (
        save_uploads_to_temp, upload_assets_to_gcs,
    )
    from image_pipeline import create_image_job, process_batch

    try:
        raw = await cases.read()
        parsed = json.loads(raw.decode("utf-8"))
        case_list = parsed.get("cases", parsed) if isinstance(parsed, dict) else parsed
        if not isinstance(case_list, list) or not case_list:
            raise ValueError("cases JSON must be a non-empty array of case objects")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid cases JSON: {e}")

    batch_id = f"imgbatch_{int(time.time())}"

    # Stage uploaded asset files and push them to GCS, then map relative paths.
    uploaded = []
    for f in files or []:
        data = await f.read()
        uploaded.append(type("U", (), {"filename": f.filename, "bytes": data})())
    relpath_to_url: Dict[str, str] = {}
    if uploaded:
        base_dir = save_uploads_to_temp(uploaded)
        relpath_to_url = upload_assets_to_gcs(base_dir, batch_id)

    def _resolve_input_image(case: dict) -> dict:
        """Rewrite a case's relative input_image to its uploaded GCS URL."""
        c = dict(case)
        ref = c.get("input_image") or c.get("reference_image")
        if ref and not (str(ref).startswith("http") or str(ref).startswith("gs://")):
            from util.asset_intake import _resolve_key
            resolved = _resolve_key(str(ref), relpath_to_url)
            if resolved:
                c["input_image"] = resolved
        return c

    pairs = []
    for case in case_list:
        rewritten = _resolve_input_image(case) if relpath_to_url else case
        job_id = create_image_job(rewritten, batch_id=batch_id)
        pairs.append((job_id, rewritten))

    background_tasks.add_task(process_batch, pairs)
    return {
        "status": "queued",
        "batch_id": batch_id,
        "job_ids": [jid for jid, _ in pairs],
        "count": len(pairs),
    }


class ImageComposeRequest(BaseModel):
    """A single composed case from the UI compose form."""
    id: Optional[str] = None
    mode: Optional[str] = "t2i"
    prompt: str
    input_image: Optional[str] = None
    matchup: Optional[str] = None
    customer: Optional[str] = None


@router.post("/api/image/compose", dependencies=[Depends(require_admin)])
async def image_compose(req: ImageComposeRequest, background_tasks: BackgroundTasks):
    """Run a single composed image case (from the compose form)."""
    from image_pipeline import create_image_job, process_batch

    case = req.dict()
    if not case.get("id"):
        case["id"] = f"compose_{int(time.time())}"
    batch_id = f"imgbatch_{int(time.time())}"
    job_id = create_image_job(case, batch_id=batch_id)
    background_tasks.add_task(process_batch, [(job_id, case)])
    return {"status": "queued", "batch_id": batch_id, "job_ids": [job_id], "count": 1}


# ===================================================================
# Jobs
# ===================================================================
@router.get("/api/image/jobs")
async def image_list_jobs(batch: Optional[str] = Query(None)):
    db = _db()
    docs = list(db.collection(IMAGE_COLLECTION).where("source", "==", "sxs_auto").stream())
    out = []
    for doc in docs:
        d = doc.to_dict()
        d["id"] = doc.id
        if batch and d.get("batch_id") != batch:
            continue
        out.append(_sign_job(d))
    out.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    return out


@router.get("/api/image/jobs/{job_id}")
async def image_get_job(job_id: str):
    db = _db()
    doc = db.collection(IMAGE_COLLECTION).document(job_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Job not found")
    d = doc.to_dict()
    d["id"] = doc.id
    return _sign_job(d)


@router.delete("/api/image/jobs/{job_id}", dependencies=[Depends(require_admin)])
async def image_delete_job(job_id: str):
    db = _db()
    ref = db.collection(IMAGE_COLLECTION).document(job_id)
    if not ref.get().exists:
        raise HTTPException(status_code=404, detail="Job not found")
    ref.delete()
    return {"status": "deleted", "job_id": job_id}


@router.post("/api/image/jobs/{job_id}/retry", dependencies=[Depends(require_admin)])
async def image_retry_job(job_id: str, background_tasks: BackgroundTasks):
    from image_pipeline import retry_job
    db = _db()
    if not db.collection(IMAGE_COLLECTION).document(job_id).get().exists:
        raise HTTPException(status_code=404, detail="Job not found")
    background_tasks.add_task(retry_job, job_id)
    return {"status": "retrying", "job_id": job_id}


@router.get("/api/image/aieval/{job_id}")
async def image_get_aieval(job_id: str):
    """Return the AI judge result for a job — revealed after a human vote."""
    db = _db()
    doc = db.collection(IMAGE_COLLECTION).document(job_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Job not found")
    d = doc.to_dict()
    return {
        "auto_eval_status": d.get("auto_eval_status"),
        "ai_eval": d.get("ai_eval", {}),
        "side_map": d.get("side_map", {}),
    }


# ===================================================================
# Blind voting pair
# ===================================================================
@router.get("/api/image/pair")
async def image_pair(
    tag: Optional[str] = Query(None),
    prompt_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
):
    """Return a random blind A/B image pair (both sides succeeded) for voting.
    Optional filters: tag (category), prompt_id (substring), search (prompt text)."""
    db = _db()
    docs = list(db.collection(IMAGE_COLLECTION).where("source", "==", "sxs_auto").stream())

    tag_l = (tag or "").strip().lower()
    pid_l = (prompt_id or "").strip().lower()
    q_l = (search or "").strip().lower()

    candidates = []
    for doc in docs:
        d = doc.to_dict()
        d["id"] = doc.id
        results = d.get("results") or {}
        a, b = results.get("A"), results.get("B")
        if not (
            isinstance(a, dict) and a.get("status") == "success" and _result_url(a)
            and isinstance(b, dict) and b.get("status") == "success" and _result_url(b)
        ):
            continue
        if tag_l and tag_l not in [str(c).lower() for c in (d.get("categories") or [])]:
            continue
        if pid_l and pid_l not in str(d.get("prompt_id", "")).lower():
            continue
        if q_l and q_l not in str(d.get("prompt", "")).lower():
            continue
        candidates.append(d)

    if not candidates:
        return {"status": "error", "message": "No image pairs ready for voting"}

    d = random.choice(candidates)
    results = d["results"]
    return {
        "job_id": d["id"],
        "prompt": d.get("prompt"),
        "prompt_id": d.get("prompt_id"),
        "categories": d.get("categories") or [],
        "customer": d.get("customer"),
        "mode": d.get("mode"),
        "input_image": _proxy(d.get("input_image")) if d.get("input_image") else None,
        # Blind: labels A/B only, NO model identity leaked.
        "variant_a": {"side": "A", "url": _proxy(_result_url(results["A"]))},
        "variant_b": {"side": "B", "url": _proxy(_result_url(results["B"]))},
    }


@router.get("/api/image/tags")
async def image_tags():
    """Distinct categories across image jobs, for the arena tag filter."""
    db = _db()
    tags = set()
    for doc in db.collection(IMAGE_COLLECTION).where("source", "==", "sxs_auto").stream():
        for t in (doc.to_dict().get("categories") or []):
            if t:
                tags.add(str(t))
    return {"status": "success", "tags": sorted(tags)}


class ImageVoteRequest(BaseModel):
    job_id: str
    winner_side: str  # "A" or "B" (or "tie")
    scores: Dict[str, int] = {}  # may be {"A": {...}, "B": {...}} or flat winner scores
    justification: str = ""
    ldap: str = "anonymous"


@router.post("/api/image/vote")
async def image_vote(req: ImageVoteRequest):
    """Store a blind human vote. Resolves winner/loser model via side_map."""
    db = _db()
    snap = db.collection(IMAGE_COLLECTION).document(req.job_id).get()
    side_map = (snap.to_dict() or {}).get("side_map", {}) if snap.exists else {}

    ws = (req.winner_side or "").strip().upper()
    winner_model = side_map.get(ws) if ws in ("A", "B") else None
    loser_side = {"A": "B", "B": "A"}.get(ws)
    loser_model = side_map.get(loser_side) if loser_side else None

    vote_id = f"imgvote_{int(time.time()*1000)}_{random.randint(100,999)}"
    db.collection(IMAGE_VOTES_COLLECTION).document(vote_id).set({
        "id": vote_id,
        "job_id": req.job_id,
        "winner_side": ws,
        "winner_model": winner_model,
        "loser_model": loser_model,
        "scores": req.scores,
        "justification": req.justification,
        "ldap": req.ldap,
        "timestamp": time.time(),
    })
    return {"status": "success", "vote_id": vote_id, "winner_model": winner_model}


# ===================================================================
# Stats / leaderboard / reports
# ===================================================================
@router.get("/api/image/stats")
async def image_stats(ldap: Optional[str] = Query(None)):
    """Win rates + per-metric averages per model, and per-matchup breakdown."""
    db = _db()
    jobs = {
        d.id: d.to_dict()
        for d in db.collection(IMAGE_COLLECTION).where("source", "==", "sxs_auto").stream()
    }
    votes = [d.to_dict() for d in db.collection(IMAGE_VOTES_COLLECTION).stream()]

    def _avg_latency():
        lat: Dict[str, dict] = {}
        for job in jobs.values():
            for res in (job.get("results") or {}).values():
                if isinstance(res, dict) and res.get("status") == "success":
                    eng = res.get("engine")
                    ms = res.get("latency_ms")
                    if eng and isinstance(ms, (int, float)):
                        lat.setdefault(eng, {"sum": 0, "count": 0})
                        lat[eng]["sum"] += ms
                        lat[eng]["count"] += 1
        return lat

    def _matchup_of(vote):
        job = jobs.get(vote.get("job_id"))
        return (job or {}).get("matchup") or "unknown"

    def _winner_scores(vote):
        sc = vote.get("scores") or {}
        ws = (vote.get("winner_side") or "").upper()
        if ws in sc and isinstance(sc[ws], dict):
            return sc[ws]
        return {k: v for k, v in sc.items() if isinstance(v, (int, float))}

    def avg_scores(score_list):
        if not score_list:
            return {}
        sums, counts = {}, {}
        for s in score_list:
            for k, v in s.items():
                if not isinstance(v, (int, float)):
                    continue
                if v == 3:  # slider default → treat as "not actively rated"
                    continue
                sums[k] = sums.get(k, 0) + v
                counts[k] = counts.get(k, 0) + 1
        return {k: round(sums[k] / counts[k], 2) for k in sums if counts.get(k)}

    def _compute(v_list):
        skus: Dict[str, dict] = {}
        matchups: Dict[str, dict] = {}
        latency = _avg_latency()

        for vote in v_list:
            wm, lm = vote.get("winner_model"), vote.get("loser_model")
            mu = _matchup_of(vote)
            matchups.setdefault(mu, {"votes": 0, "by_model": {}})
            matchups[mu]["votes"] += 1
            for mid in (wm, lm):
                if mid and mid not in skus:
                    skus[mid] = {"wins": 0, "total": 0, "scores": []}
                if mid:
                    bm = matchups[mu]["by_model"].setdefault(mid, {"wins": 0, "total": 0})
            if wm:
                skus[wm]["wins"] += 1
                skus[wm]["total"] += 1
                matchups[mu]["by_model"][wm]["wins"] += 1
                matchups[mu]["by_model"][wm]["total"] += 1
                sc = _winner_scores(vote)
                if sc:
                    skus[wm]["scores"].append(sc)
            if lm:
                skus[lm]["total"] += 1
                matchups[mu]["by_model"][lm]["total"] += 1

        leaderboard = []
        for mid, data in skus.items():
            wr = (data["wins"] / data["total"]) * 100 if data["total"] else 0
            lat = latency.get(mid, {})
            lms = round(lat["sum"] / lat["count"]) if lat.get("count") else 0
            leaderboard.append({
                "model_id": mid,
                "win_rate": round(wr, 1),
                "wins": data["wins"],
                "total": data["total"],
                "latency_ms": lms,
                "scores": avg_scores(data["scores"]),
            })

        matchup_out = []
        for mu, data in matchups.items():
            entry = {"matchup": mu, "votes": data["votes"], "models": []}
            for mid, md in data["by_model"].items():
                r = (md["wins"] / md["total"]) * 100 if md["total"] else 0
                entry["models"].append({
                    "model_id": mid, "wins": md["wins"], "total": md["total"],
                    "win_rate": round(r, 1),
                })
            matchup_out.append(entry)

        return {
            "total_evals": len(v_list),
            "skus": sorted(leaderboard, key=lambda x: x["win_rate"], reverse=True),
            "matchups": matchup_out,
        }

    result = {"global": _compute(votes)}
    if ldap:
        result["user"] = _compute([v for v in votes if v.get("ldap", "anonymous") == ldap])
    return result


@router.get("/api/image/leaderboard")
async def image_leaderboard(ldap: Optional[str] = Query(None)):
    """Alias of stats for the brief's `/api/image/leaderboard` path."""
    return await image_stats(ldap=ldap)


@router.get("/api/image/leaderboard/users")
async def image_user_leaderboard():
    db = _db()
    counts = Counter()
    for d in db.collection(IMAGE_VOTES_COLLECTION).stream():
        v = d.to_dict()
        ld = v.get("ldap", "")
        if ld and ld != "anonymous":
            counts[ld] += 1
    top_10 = sorted(
        [{"ldap": k, "count": v} for k, v in counts.items()],
        key=lambda x: x["count"], reverse=True,
    )[:10]
    return {"status": "success", "leaderboard": top_10}


@router.get("/api/image/report.json")
async def image_report_json(batch: Optional[str] = Query(None)):
    return await image_list_jobs(batch=batch)


@router.get("/api/image/report.csv")
async def image_report_csv(batch: Optional[str] = Query(None)):
    import csv
    jobs = await image_list_jobs(batch=batch)
    metrics = ["prompt_following", "aesthetic", "detail", "artifact_free", "edit_fidelity"]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["job_id", "customer", "case_id", "matchup", "mode", "prompt", "side",
         "engine", "status"]
        + [m + "_score" for m in metrics]
        + ["overall_score", "ai_winner_engine"]
    )
    for j in jobs:
        ai = j.get("ai_eval", {}) or {}
        for side in ("A", "B"):
            res = (j.get("results") or {}).get(side) or {}
            ai_side = ai.get(side) or {}
            row = [
                j.get("id"), j.get("customer"), j.get("prompt_id"),
                j.get("matchup"), j.get("mode"), (j.get("prompt") or "")[:300],
                side, res.get("engine"), res.get("status"),
            ]
            for m in metrics:
                row.append(ai_side.get(m, ""))
            row.append(ai_side.get("overall_score", ""))
            row.append(ai.get("winner_engine", ""))
            writer.writerow(row)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=image_sxs_report.csv"},
    )


# ===================================================================
# Image media proxy (image-aware; supports Range requests)
# ===================================================================
@router.get("/api/image/media")
async def image_media_proxy(url: str = Query(...), request: Request = None):
    from util.gcs_utils import https_to_gs, get_upload_client

    try:
        fixed = url
        if fixed.startswith("gs:/") and not fixed.startswith("gs://"):
            fixed = "gs://" + fixed[4:]
        gs_uri = https_to_gs(fixed)
        if not gs_uri.startswith("gs://"):
            raise HTTPException(status_code=400, detail="Only GCS URLs are allowed")

        parts = gs_uri.replace("gs://", "").split("/")
        bucket_name = parts[0]
        blob_name = "/".join(parts[1:])

        client = get_upload_client()
        blob = client.bucket(bucket_name).blob(blob_name)
        blob.reload()
        total_size = blob.size

        lower = url.lower()
        ct = "image/png"
        if ".jpg" in lower or ".jpeg" in lower:
            ct = "image/jpeg"
        elif ".webp" in lower:
            ct = "image/webp"
        elif ".gif" in lower:
            ct = "image/gif"

        range_header = request.headers.get("range") if request else None
        if range_header and total_size:
            rng = range_header.replace("bytes=", "").split("-")
            start = int(rng[0]) if rng[0] else 0
            end = int(rng[1]) if len(rng) > 1 and rng[1] else total_size - 1
            end = min(end, total_size - 1)
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

        def stream_blob():
            with blob.open("rb") as f:
                while True:
                    chunk = f.read(1024 * 1024)
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
        raise
    except Exception as e:
        print(f"[image_routes] Error proxying media {url}: {e}")
        raise HTTPException(status_code=404, detail="Failed to load media")
