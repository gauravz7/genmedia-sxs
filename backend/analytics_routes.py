"""Stats, leaderboards and the cross-modality analytics.

Reads every modality's collections, so it is the one place that is deliberately
NOT modality-isolated."""

import os
from collections import Counter
from typing import Dict, Optional

from fastapi import (APIRouter, Query)

from config import (SXS_COLLECTION,
                    SXS_VOTES_COLLECTION)
from store import jobs_manager, votes_manager

router = APIRouter()


@router.get("/api/evaluation/stats")
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


@router.get("/api/leaderboard/users")
async def get_user_leaderboard():
    counts = Counter()
    for v in votes_manager.votes:
        ldap = getattr(v, "ldap", "")
        if ldap and ldap != "anonymous":
            counts[ldap] += 1
    top_10 = sorted([{"ldap": k, "count": v} for k, v in counts.items()], key=lambda x: x["count"], reverse=True)[:10]
    return {"status": "success", "leaderboard": top_10}


@router.get("/api/sxs/stats")
async def sxs_stats(ldap: Optional[str] = Query(None), tag: Optional[str] = Query(None)):
    """Win rates / leaderboard for the isolated SxS test DB (sxs_votes + sxs_jobs).
    Scores use the Core-5 1-5 rubric (no default-skip).

    Optional `tag` filters to jobs whose categories include that tag (and, in turn,
    restricts votes to those jobs)."""
    from google.cloud import firestore as _fs
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
    jobs = {
        d.id: d.to_dict()
        for d in db.collection(SXS_COLLECTION).where("source", "==", "sxs_auto").stream()
    }
    tag_l = (tag or "").strip().lower()
    if tag_l:
        jobs = {
            jid: j for jid, j in jobs.items()
            if tag_l in [str(c).lower() for c in (j.get("categories") or [])]
        }
    votes = [d.to_dict() for d in db.collection(SXS_VOTES_COLLECTION).stream()]
    if tag_l:
        votes = [v for v in votes if v.get("job_id") in jobs]

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

    def _tags_of(vote):
        return [str(c) for c in (jobs.get(vote.get("job_id")) or {}).get("categories") or []]

    def _by_tag(v_list):
        """Per-tag → per-model win rates (ties credit both winner and loser)."""
        tags: Dict[str, dict] = {}
        for vote in v_list:
            wm, lm = vote.get("winner_model"), vote.get("loser_model")
            is_tie = (vote.get("winner_side") or "").strip().lower() == "tie"
            for tag in _tags_of(vote):
                t = tags.setdefault(tag, {"votes": 0, "by_model": {}})
                t["votes"] += 1
                for mid in (wm, lm):
                    if mid:
                        t["by_model"].setdefault(mid, {"wins": 0, "total": 0})
                if is_tie:
                    for mid in (wm, lm):
                        if mid:
                            t["by_model"][mid]["wins"] += 1
                            t["by_model"][mid]["total"] += 1
                else:
                    if wm:
                        t["by_model"][wm]["wins"] += 1
                        t["by_model"][wm]["total"] += 1
                    if lm:
                        t["by_model"][lm]["total"] += 1
        out = []
        for tag, data in tags.items():
            models = [
                {"model_id": mid, "wins": md["wins"], "total": md["total"],
                 "win_rate": round((md["wins"] / md["total"]) * 100, 1) if md["total"] else 0.0}
                for mid, md in data["by_model"].items()
            ]
            models.sort(key=lambda x: x["win_rate"], reverse=True)
            out.append({"tag": tag, "votes": data["votes"], "models": models})
        out.sort(key=lambda x: x["votes"], reverse=True)
        return out

    def _bundle(v_list):
        out = _compute(v_list)
        out["by_tag"] = _by_tag(v_list)
        return out

    result = {"global": _bundle(votes)}
    if ldap:
        result["user"] = _bundle([v for v in votes if v.get("ldap", "anonymous") == ldap])
    return result


@router.get("/api/sxs/tags")
async def sxs_tags():
    """Distinct categories across the SxS video jobs (sxs_jobs), for the video
    analytics tag filter. Sourced from the same collection the stats use so the
    picker and the by-tag matrix always agree."""
    from google.cloud import firestore as _fs
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
    tags = set()
    for doc in db.collection(SXS_COLLECTION).where("source", "==", "sxs_auto").stream():
        for t in (doc.to_dict().get("categories") or []):
            if t:
                tags.add(str(t))
    return {"status": "success", "tags": sorted(tags)}


@router.get("/api/sxs/leaderboard/users")
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


@router.get("/api/analytics/latency")
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


def _wilson(k: int, n: int, z: float = 1.96):
    """Wilson score interval for a binomial proportion. Returns (low, p, high)."""
    if n <= 0:
        return (0.0, 0.0, 0.0)
    import math
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, center - half), p, min(1.0, center + half))


def _is_google_engine(engine: str) -> bool:
    e = str(engine or "").lower()
    return any(k in e for k in ("gemini", "imagen", "veo", "omni", "nano", "banana", "doubao-google"))


def _engine_family(engine: str) -> str:
    return "google" if _is_google_engine(engine) else "competitor"


@router.get("/api/benchmark/winmap")
async def benchmark_winmap(min_n: int = 10):
    """Where do Google models win? Aggregates AI-judge verdicts across image,
    TTS and video (Google-vs-competitor pairs only) and reports Google's
    win-rate with Wilson CIs + n, sliced by category, language, and modality.
    Segments whose CI clears 50% are surfaced as significant leads / trails.
    (Human votes are sparse; this uses the AI judge — pair with /agreement.)"""
    from google.cloud import firestore as _fs
    from sxs_pipeline import modality_to_type
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))

    # seg_key -> [google_wins, google_vs_comp_total]
    segs: Dict[str, list] = {}

    def bump(dim: str, seg: str, won: bool):
        key = f"{dim}\x1f{seg}"
        a = segs.setdefault(key, [0, 0])
        a[1] += 1
        if won:
            a[0] += 1

    def record(sides: list, winner: str, categories, language, modality):
        # sides = list of engine ids present; need exactly one google + one competitor
        fams = [_engine_family(s) for s in sides if s]
        if fams.count("google") != 1 or fams.count("competitor") != 1 or not winner:
            return
        won = _is_google_engine(winner)
        bump("overall", "all", won)
        bump("modality", modality or "?", won)
        if language:
            bump("language", str(language), won)
        for c in (categories or []):
            cs = str(c)
            if cs and not cs.lower().startswith("len:"):
                bump("category", cs, won)

    # Image
    for d in db.collection(os.getenv("IMAGE_COLLECTION", "image_jobs")).stream():
        j = d.to_dict(); ai = j.get("ai_eval") or {}
        sm = j.get("side_map") or {}
        record(list(sm.values()), ai.get("winner_engine"),
               j.get("categories"), None, (j.get("mode") or "t2i"))
    # TTS
    for d in db.collection(os.getenv("TTS_COLLECTION", "tts_jobs")).stream():
        j = d.to_dict(); ai = j.get("ai_eval") or {}
        sm = j.get("side_map") or {}
        record(list(sm.values()), ai.get("winner_engine"),
               j.get("categories"), j.get("language"), "tts")
    # Video: winner = Creative-Director verdict (the video eval); fall back to
    # highest Core-5 overall for older jobs.
    for d in db.collection(os.getenv("SXS_COLLECTION", "sxs_jobs")).where("source", "==", "sxs_auto").stream():
        j = d.to_dict(); autos = j.get("auto_evals") or {}
        scored = {k: v.get("overall_score") for k, v in autos.items()
                  if isinstance(v, dict) and isinstance(v.get("overall_score"), (int, float))}
        de = j.get("director_eval") or {}
        winner = de.get("winner_model") or (max(scored, key=scored.get) if len(scored) >= 2 else None)
        sides = list(scored.keys()) or [r.get("engine") or r.get("model")
                                        for r in (j.get("results") or {}).values() if isinstance(r, dict)]
        if len([s for s in sides if s]) < 2 or not winner:
            continue
        record(sides, winner, j.get("categories"),
               j.get("language"), modality_to_type(j.get("modality") or "t2v"))

    def rows_for(dim: str, apply_min: bool = True):
        out = []
        pfx = f"{dim}\x1f"
        for key, (wins, n) in segs.items():
            if not key.startswith(pfx):
                continue
            # Skip thin segments — a CI on n<min_n is not meaningful.
            if apply_min and n < min_n:
                continue
            lo, p, hi = _wilson(wins, n)
            verdict = "lead" if lo > 0.5 else ("trail" if hi < 0.5 else "tie")
            out.append({
                "segment": key[len(pfx):], "n": n,
                "win_rate": round(p * 100, 1),
                "ci_low": round(lo * 100, 1), "ci_high": round(hi * 100, 1),
                "verdict": verdict,
            })
        return sorted(out, key=lambda x: (-x["n"], -x["win_rate"]))

    by_cat = rows_for("category")
    by_lang = rows_for("language")
    by_mod = rows_for("modality")
    overall = rows_for("overall")
    all_segments = by_cat + by_lang + by_mod
    leads = sorted([s for s in all_segments if s["verdict"] == "lead"],
                   key=lambda x: -x["win_rate"])
    trails = sorted([s for s in all_segments if s["verdict"] == "trail"],
                    key=lambda x: x["win_rate"])
    return {
        "overall": overall[0] if overall else {"win_rate": 0, "ci_low": 0, "ci_high": 0, "n": 0},
        "by_category": by_cat, "by_language": by_lang, "by_modality": by_mod,
        "leads": leads, "trails": trails,
        "note": "Google win-rate from the AI judge on Google-vs-competitor pairs; CI = 95% Wilson.",
    }


@router.get("/api/analytics/agreement")
async def analytics_agreement():
    """How often does the AI judge agree with human blind votes? Per modality:
    of jobs that have BOTH a human vote (winner_model) and an AI verdict
    (ai_eval.winner_engine / director), the % where they pick the same engine."""
    from google.cloud import firestore as _fs
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))

    def ai_winner_map(coll: str):
        m = {}
        for d in db.collection(coll).stream():
            j = d.to_dict()
            # video: Creative-Director verdict; image/tts: ai_eval winner; else Core-5.
            w = (j.get("director_eval") or {}).get("winner_model") or (j.get("ai_eval") or {}).get("winner_engine")
            if not w:
                autos = j.get("auto_evals") or {}
                scored = {k: v.get("overall_score") for k, v in autos.items()
                          if isinstance(v, dict) and isinstance(v.get("overall_score"), (int, float))}
                w = max(scored, key=scored.get) if len(scored) >= 2 else None
            if w:
                m[d.id] = w
        return m

    out = {}
    total_agree = total_n = 0
    for label, coll, votes_coll in (
        ("image", os.getenv("IMAGE_COLLECTION", "image_jobs"), os.getenv("IMAGE_VOTES_COLLECTION", "image_votes")),
        ("tts", os.getenv("TTS_COLLECTION", "tts_jobs"), os.getenv("TTS_VOTES_COLLECTION", "tts_votes")),
        ("video", os.getenv("SXS_COLLECTION", "sxs_jobs"), SXS_VOTES_COLLECTION),
    ):
        aiw = ai_winner_map(coll)
        agree = n = 0
        for d in db.collection(votes_coll).stream():
            v = d.to_dict()
            hw = v.get("winner_model")
            jid = v.get("job_id")
            if hw and jid in aiw:
                n += 1
                if str(hw) == str(aiw[jid]):
                    agree += 1
        pct = round(agree / n * 100, 1) if n else None
        out[label] = {"agree": agree, "n": n, "pct": pct}
        total_agree += agree; total_n += n
    out["overall"] = {"agree": total_agree, "n": total_n,
                      "pct": round(total_agree / total_n * 100, 1) if total_n else None}
    return out


@router.get("/api/votes/count")
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


@router.get("/api/leaderboard")
async def full_leaderboard():
    """Voter leaderboard: top overall + top per modality (video / image / tts).

    Anti-gaming: the blind A/B label is randomized per job, so a genuine voter's
    A vs B split trends ~50/50 over many votes. A voter who almost always picks
    the SAME side is voting blindly to farm the leaderboard — we exclude anyone
    with >= MIN_DECISIVE non-tie votes whose dominant side is >= ONE_SIDED of them.
    """
    from google.cloud import firestore as _fs
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))

    MIN_DECISIVE = 5          # need enough A/B votes before judging one-sidedness
    ONE_SIDED = 0.9           # >=90% on one side = suspected blind voting

    # modality -> collections that feed it ("votes" = legacy video).
    MOD_COLLECTIONS = {
        "video": (SXS_VOTES_COLLECTION, "votes"),
        "image": ("image_votes",),
        "tts": ("tts_votes",),
    }

    # Per-voter tally: counts per modality + side distribution (a/b/tie).
    voters: Dict[str, dict] = {}
    for modality, colls in MOD_COLLECTIONS.items():
        for coll in colls:
            try:
                docs = db.collection(coll).stream()
            except Exception:
                continue
            for d in docs:
                v = d.to_dict() or {}
                ld = v.get("ldap")
                if not ld or str(ld).lower() in ("anonymous", "global"):
                    continue
                ld = str(ld)
                rec = voters.setdefault(ld, {
                    "ldap": ld, "total": 0,
                    "video": 0, "image": 0, "tts": 0,
                    "a": 0, "b": 0, "tie": 0,
                })
                rec[modality] += 1
                rec["total"] += 1
                side = str(v.get("winner_side") or "").strip().lower()
                if side in ("a", "b", "tie"):
                    rec[side] += 1

    excluded = []
    clean = []
    for rec in voters.values():
        decisive = rec["a"] + rec["b"]
        dom = max(rec["a"], rec["b"])
        frac = (dom / decisive) if decisive else 0.0
        if decisive >= MIN_DECISIVE and frac >= ONE_SIDED:
            excluded.append({
                "ldap": rec["ldap"], "total": rec["total"],
                "dominant_side": "A" if rec["a"] >= rec["b"] else "B",
                "dominant_pct": round(frac * 100, 1),
            })
        else:
            clean.append(rec)

    def _top(key, n=50):
        rows = [r for r in clean if r[key] > 0]
        rows.sort(key=lambda r: r[key], reverse=True)
        return [
            {"ldap": r["ldap"], "count": r[key], "total": r["total"],
             "video": r["video"], "image": r["image"], "tts": r["tts"]}
            for r in rows[:n]
        ]

    return {
        "status": "success",
        "overall": _top("total"),
        "by_modality": {
            "video": _top("video"),
            "image": _top("image"),
            "tts": _top("tts"),
        },
        "excluded": sorted(excluded, key=lambda x: x["total"], reverse=True),
        "rules": {"min_decisive": MIN_DECISIVE, "one_sided_pct": int(ONE_SIDED * 100)},
    }


@router.get("/api/votes/leaderboard")
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
