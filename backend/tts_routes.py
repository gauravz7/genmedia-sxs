"""TTS SxS API routes (self-contained APIRouter).

Mirrors the video `/api/sxs/*` endpoints, scoped to the isolated `tts_jobs` /
`tts_votes` Firestore collections, so the TTS modality cannot affect the video
flow. Wire it in main.py with:

    from tts_routes import router as tts_router
    app.include_router(tts_router)

Does NOT import main.py — `require_admin` and the admin-token derivation are
re-implemented locally (identical token: sha256("project-pulse-sxs:v1:" +
ADMIN_USER + ":" + ADMIN_PASS)).

Audio is served through a LOCAL media proxy (`/api/tts/media`) that sets the
correct audio content-type and supports Range requests — the existing
`/api/media` proxy only knows image/video MIME types.
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
TTS_COLLECTION = os.getenv("TTS_COLLECTION", "tts_jobs")
TTS_VOTES_COLLECTION = os.getenv("TTS_VOTES_COLLECTION", "tts_votes")

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS")
_ADMIN_TOKEN_SALT = "project-pulse-sxs:v1"

router = APIRouter(prefix="/api/tts")


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
    if "/api/tts/media?url=" in u:
        return urllib.parse.unquote(u.split("/api/tts/media?url=")[-1])
    if "X-Goog-Signature" in u or "?X-Goog-Algorithm" in u:
        return u.split("?")[0]
    return u


def _proxy(u: Optional[str]) -> Optional[str]:
    """Return a browser-playable URL routed through the local audio proxy."""
    if not u:
        return u
    if "/api/tts/media?url=" in u:
        return u
    if _is_gcs(u):
        return f"/api/tts/media?url={urllib.parse.quote(_normalize(u))}"
    return u


def _result_url(res: dict) -> Optional[str]:
    if not isinstance(res, dict):
        return None
    return res.get("url") or res.get("gcs_url") or (res.get("result") or {}).get("url")


def _sign_job(d: dict) -> dict:
    """Sign/proxy the audio URLs of a TTS job doc for the browser."""
    for _label, res in (d.get("results") or {}).items():
        if isinstance(res, dict):
            if res.get("url"):
                res["url"] = _proxy(res["url"])
            if res.get("gcs_url"):
                res["gcs_url"] = _proxy(res["gcs_url"])
            if isinstance(res.get("result"), dict) and res["result"].get("url"):
                res["result"]["url"] = _proxy(res["result"]["url"])
    return d


# ===================================================================
# Upload / run
# ===================================================================
@router.post("/upload", dependencies=[Depends(require_admin)])
async def tts_upload(
    background_tasks: BackgroundTasks,
    cases: UploadFile = File(...),
):
    """Upload a TTS cases JSON; create one job per case and schedule background
    Gemini + ElevenLabs generation followed by the AI audio judge."""
    from tts_pipeline import create_tts_job, process_tts_batch

    try:
        raw = await cases.read()
        parsed = json.loads(raw.decode("utf-8"))
        case_list = parsed.get("cases", parsed) if isinstance(parsed, dict) else parsed
        if not isinstance(case_list, list) or not case_list:
            raise ValueError("cases JSON must be a non-empty array of case objects")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid cases JSON: {e}")

    batch_id = f"ttsbatch_{int(time.time())}"
    pairs = []
    for case in case_list:
        job_id = create_tts_job(case, batch_id=batch_id)
        pairs.append((job_id, case))

    background_tasks.add_task(process_tts_batch, pairs)
    return {
        "status": "queued",
        "batch_id": batch_id,
        "job_ids": [jid for jid, _ in pairs],
        "count": len(pairs),
    }


class TtsComposeRequest(BaseModel):
    """A single composed case from the UI compose form."""
    id: Optional[str] = None
    text: str
    voice: str = "Kore"
    style_prompt: Optional[str] = None
    language: Optional[str] = None
    mode: Optional[str] = "single"
    speakers: Optional[List[dict]] = None
    customer: Optional[str] = None


@router.post("/compose", dependencies=[Depends(require_admin)])
async def tts_compose(req: TtsComposeRequest, background_tasks: BackgroundTasks):
    """Run a single composed case (from the compose form)."""
    from tts_pipeline import create_tts_job, process_tts_batch

    case = req.dict()
    if not case.get("id"):
        case["id"] = f"compose_{int(time.time())}"
    batch_id = f"ttsbatch_{int(time.time())}"
    job_id = create_tts_job(case, batch_id=batch_id)
    background_tasks.add_task(process_tts_batch, [(job_id, case)])
    return {"status": "queued", "batch_id": batch_id, "job_ids": [job_id], "count": 1}


# ===================================================================
# Jobs
# ===================================================================
@router.get("/jobs")
async def tts_list_jobs(batch: Optional[str] = Query(None)):
    db = _db()
    docs = list(db.collection(TTS_COLLECTION).where("source", "==", "sxs_auto").stream())
    out = []
    for doc in docs:
        d = doc.to_dict()
        d["id"] = doc.id
        if batch and d.get("batch_id") != batch:
            continue
        out.append(_sign_job(d))
    out.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    return out


@router.get("/jobs/{job_id}")
async def tts_get_job(job_id: str):
    db = _db()
    doc = db.collection(TTS_COLLECTION).document(job_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Job not found")
    d = doc.to_dict()
    d["id"] = doc.id
    return _sign_job(d)


@router.delete("/jobs/{job_id}", dependencies=[Depends(require_admin)])
async def tts_delete_job(job_id: str):
    db = _db()
    ref = db.collection(TTS_COLLECTION).document(job_id)
    if not ref.get().exists:
        raise HTTPException(status_code=404, detail="Job not found")
    ref.delete()
    return {"status": "deleted", "job_id": job_id}


@router.post("/jobs/{job_id}/retry", dependencies=[Depends(require_admin)])
async def tts_retry_job(job_id: str, background_tasks: BackgroundTasks):
    from tts_pipeline import retry_tts_job
    db = _db()
    if not db.collection(TTS_COLLECTION).document(job_id).get().exists:
        raise HTTPException(status_code=404, detail="Job not found")
    background_tasks.add_task(retry_tts_job, job_id)
    return {"status": "retrying", "job_id": job_id}


@router.get("/aieval/{job_id}")
async def tts_get_aieval(job_id: str):
    """Return the AI audio-judge result for a job — revealed after a human vote."""
    db = _db()
    doc = db.collection(TTS_COLLECTION).document(job_id).get()
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
@router.get("/pair")
async def tts_pair():
    """Return a random blind A/B TTS pair (both sides succeeded) for voting."""
    db = _db()
    docs = list(db.collection(TTS_COLLECTION).where("source", "==", "sxs_auto").stream())

    candidates = []
    for doc in docs:
        d = doc.to_dict()
        d["id"] = doc.id
        results = d.get("results") or {}
        a, b = results.get("A"), results.get("B")
        if (
            isinstance(a, dict) and a.get("status") == "success" and _result_url(a)
            and isinstance(b, dict) and b.get("status") == "success" and _result_url(b)
        ):
            candidates.append(d)

    if not candidates:
        return {"status": "error", "message": "No TTS pairs ready for voting"}

    d = random.choice(candidates)
    results = d["results"]
    return {
        "job_id": d["id"],
        "text": d.get("text") or d.get("prompt"),
        "style_prompt": d.get("style_prompt"),
        "customer": d.get("customer"),
        "mode": d.get("mode"),
        "language": d.get("language"),
        # Blind: labels A/B only, NO engine identity leaked.
        "variant_a": {"side": "A", "url": _proxy(_result_url(results["A"]))},
        "variant_b": {"side": "B", "url": _proxy(_result_url(results["B"]))},
    }


class TtsVoteRequest(BaseModel):
    job_id: str
    winner_side: str  # "A" or "B" (or "tie")
    scores: Dict[str, int] = {}  # may be {"A": {...}, "B": {...}} or flat winner scores
    justification: str = ""
    ldap: str = "anonymous"


@router.post("/vote")
async def tts_vote(req: TtsVoteRequest):
    """Store a blind human vote. Resolves winner/loser engine via side_map."""
    db = _db()
    snap = db.collection(TTS_COLLECTION).document(req.job_id).get()
    side_map = (snap.to_dict() or {}).get("side_map", {}) if snap.exists else {}

    ws = (req.winner_side or "").strip().upper()
    winner_engine = side_map.get(ws) if ws in ("A", "B") else None
    loser_side = {"A": "B", "B": "A"}.get(ws)
    loser_engine = side_map.get(loser_side) if loser_side else None

    vote_id = f"ttsvote_{int(time.time()*1000)}_{random.randint(100,999)}"
    db.collection(TTS_VOTES_COLLECTION).document(vote_id).set({
        "id": vote_id,
        "job_id": req.job_id,
        "winner_side": ws,
        "winner_model": winner_engine,
        "loser_model": loser_engine,
        "scores": req.scores,
        "justification": req.justification,
        "ldap": req.ldap,
        "timestamp": time.time(),
    })
    return {"status": "success", "vote_id": vote_id, "winner_model": winner_engine}


# ===================================================================
# Stats / leaderboard / reports
# ===================================================================
@router.get("/stats")
async def tts_stats(ldap: Optional[str] = Query(None)):
    """Win rates + per-metric averages for Gemini vs ElevenLabs."""
    db = _db()
    jobs = {
        d.id: d.to_dict()
        for d in db.collection(TTS_COLLECTION).where("source", "==", "sxs_auto").stream()
    }
    votes = [d.to_dict() for d in db.collection(TTS_VOTES_COLLECTION).stream()]

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

    def _compute(v_list):
        skus: Dict[str, dict] = {}
        latency = _avg_latency()

        def _winner_scores(vote):
            """Return per-metric scores for the winning engine, if any."""
            sc = vote.get("scores") or {}
            ws = (vote.get("winner_side") or "").upper()
            if ws in sc and isinstance(sc[ws], dict):
                return sc[ws]
            # flat scores assumed to be for the winner
            flat = {k: v for k, v in sc.items() if isinstance(v, (int, float))}
            return flat

        for vote in v_list:
            wm, lm = vote.get("winner_model"), vote.get("loser_model")
            for mid in (wm, lm):
                if mid and mid not in skus:
                    skus[mid] = {"wins": 0, "total": 0, "scores": []}
            if wm:
                skus[wm]["wins"] += 1
                skus[wm]["total"] += 1
                ws = _winner_scores(vote)
                if ws:
                    skus[wm]["scores"].append(ws)
            if lm:
                skus[lm]["total"] += 1

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

        return {
            "total_evals": len(v_list),
            "skus": sorted(leaderboard, key=lambda x: x["win_rate"], reverse=True),
        }

    result = {"global": _compute(votes)}
    if ldap:
        result["user"] = _compute([v for v in votes if v.get("ldap", "anonymous") == ldap])
    return result


@router.get("/leaderboard/users")
async def tts_user_leaderboard():
    db = _db()
    counts = Counter()
    for d in db.collection(TTS_VOTES_COLLECTION).stream():
        v = d.to_dict()
        ld = v.get("ldap", "")
        if ld and ld != "anonymous":
            counts[ld] += 1
    top_10 = sorted(
        [{"ldap": k, "count": v} for k, v in counts.items()],
        key=lambda x: x["count"], reverse=True,
    )[:10]
    return {"status": "success", "leaderboard": top_10}


@router.get("/leaderboard")
async def tts_leaderboard(ldap: Optional[str] = Query(None)):
    """Engine win-rate leaderboard (Gemini vs ElevenLabs). Thin alias over the
    `/stats` computation so the UI has a dedicated endpoint."""
    stats = await tts_stats(ldap=ldap)
    g = stats.get("global", {})
    return {
        "status": "success",
        "total_evals": g.get("total_evals", 0),
        "leaderboard": g.get("skus", []),
    }


@router.get("/voices")
async def tts_voices():
    """Return the available voices for the compose form: the 30 prebuilt Gemini
    voices and the ElevenLabs named voices."""
    from providers.gemini_tts_provider import PREBUILT_VOICES, DEFAULT_VOICE
    from providers.elevenlabs_provider import VOICE_MAP, DEFAULT_VOICE_NAME

    return {
        "gemini": {
            "engine": "gemini-3.1-flash-tts-preview",
            "default": DEFAULT_VOICE,
            "voices": list(PREBUILT_VOICES),
        },
        "elevenlabs": {
            "engine": "elevenlabs-multilingual-v2",
            "default": DEFAULT_VOICE_NAME,
            "voices": [{"name": k, "voice_id": v} for k, v in VOICE_MAP.items()],
        },
    }


@router.get("/report.json")
async def tts_report_json(batch: Optional[str] = Query(None)):
    return await tts_list_jobs(batch=batch)


@router.get("/report.csv")
async def tts_report_csv(batch: Optional[str] = Query(None)):
    import csv
    jobs = await tts_list_jobs(batch=batch)
    metrics = [
        "naturalness", "style_adherence", "expressiveness",
        "pacing", "pronunciation_clarity",
    ]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["job_id", "customer", "case_id", "text", "side", "engine", "status"]
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
                (j.get("text") or "")[:300], side, res.get("engine"),
                res.get("status"),
            ]
            for m in metrics:
                row.append(ai_side.get(m, ""))
            row.append(ai_side.get("overall_score", ""))
            row.append(ai.get("winner_engine", ""))
            writer.writerow(row)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=tts_sxs_report.csv"},
    )


# ===================================================================
# Audio media proxy (audio-aware; supports Range requests)
# ===================================================================
@router.get("/media")
async def tts_media_proxy(url: str = Query(...), request: Request = None):
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
        ct = "audio/wav"
        if ".mp3" in lower:
            ct = "audio/mpeg"
        elif ".ogg" in lower:
            ct = "audio/ogg"
        elif ".wav" in lower:
            ct = "audio/wav"

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
        print(f"[tts_routes] Error proxying media {url}: {e}")
        raise HTTPException(status_code=404, detail="Failed to load media")
