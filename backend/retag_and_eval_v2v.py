"""(1) Normalize tags on the imported v2v jobs (+ add a 'v2v-edit' grouping tag),
   (2) run the pairwise Creative-Director AI judge (Seedance vs Omni) on each.
No generation — evaluates the already-imported clips."""
import os, tempfile, time
from sxs_pipeline import _get_firestore_client, EVAL_COLLECTION
from util.gcs_utils import download_blob_to_bytes
from video_evaluator_sdk import run_director_pairwise, EVAL_MODEL

BATCH = "v2v_bench_dashtoon_x3"

CLEAN = {
    "9:16 <-> 16:9 aspect changes": "Aspect Ratio",
    "Change camera angles / lighting / background": "Camera/Lighting/BG",
    "Change character action/emotion": "Action & Emotion",
    "Change lipsync / dubbing": "Lipsync/Dubbing",
    "Change minor character features": "Minor Features",
    "Change prop + character interaction": "Prop + Character",
    "Change prop only": "Prop Only",
    "Character consistency of input image": "Character Consistency",
    "SFX in a scene (+ reaction)": "SFX & Reaction",
    "Swap only character positions": "Position Swap",
    "VFX requests": "VFX",
    "Audio": "Audio",
}

db = _get_firestore_client()
docs = list(db.collection(EVAL_COLLECTION).where("batch_id", "==", BATCH).stream())
print(f"jobs: {len(docs)}")

def _to_temp(url):
    data = download_blob_to_bytes(url)
    fd, path = tempfile.mkstemp(suffix=".mp4")
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return path

done = 0
for d in docs:
    j = d.to_dict()
    jid = j["id"]

    # --- (1) retag ---
    newcats = [CLEAN.get(c, c) for c in (j.get("categories") or [])]
    if "v2v-edit" not in newcats:
        newcats.append("v2v-edit")

    # --- (1b) canonicalize the Seedance model key -> seedance-2-0-r2v ---
    res = dict(j.get("results", {}))
    for k in list(res.keys()):
        if "seedance" in k and k != "seedance-2-0-r2v":
            res["seedance-2-0-r2v"] = res.pop(k)
    d.reference.update({"categories": newcats, "results": res})

    # --- (2) pairwise AI judge (A=Seedance, B=Omni) ---
    sk = next((k for k in res if "seedance" in k), None)
    ok = next((k for k in res if "omni" in k), None)
    if not (sk and ok):
        print(f"  {jid}: missing a side, skip eval"); continue
    tmp = []
    try:
        a = _to_temp(res[sk]["url"]); b = _to_temp(res[ok]["url"]); tmp += [a, b]
        rep = run_director_pairwise(a, b, j.get("prompt", ""))
        if rep:
            v = (rep.get("verdict") or "").strip().upper()
            rep["winner_model"] = sk if v == "A" else (ok if v == "B" else None)
            rep["video_a"] = sk; rep["video_b"] = ok
            rep["model"] = EVAL_MODEL; rep["evaluated_at"] = time.time()
            d.reference.update({"director_eval": rep, "auto_eval_status": "done"})
            done += 1
            print(f"  {jid}: verdict={v} winner={rep['winner_model']}  tags={newcats}")
        else:
            print(f"  {jid}: no verdict")
    except Exception as e:
        d.reference.update({"auto_eval_status": "error", "auto_eval_error": str(e)})
        print(f"  {jid}: eval error {str(e)[:100]}")
    finally:
        for p in tmp:
            try: os.remove(p)
            except OSError: pass

print(f"\nDONE: retagged {len(docs)}, AI-judged {done}/{len(docs)}")
