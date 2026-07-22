"""Re-run all AI evals on the new standardized gemini-3.5-flash judge.
Only evaluates jobs that have >=2 successful sides (real pairs); single-success
jobs are skipped per instruction.
"""
import os, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.cloud import firestore

db = firestore.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))

def successful_sides(job):
    return [s for s, r in (job.get("results") or {}).items()
            if isinstance(r, dict) and r.get("status") == "success"]

def collect(coll):
    out = []
    for d in db.collection(coll).stream():
        j = d.to_dict()
        if coll == "sxs_jobs" and j.get("source") != "sxs_auto":
            continue
        if len(successful_sides(j)) >= 2:
            out.append(d.id)
    return out

def run_one(kind, jid):
    try:
        if kind == "image":
            import image_evaluator; image_evaluator.run_image_evaluation(jid)
        elif kind == "tts":
            import tts_evaluator; tts_evaluator.run_tts_evaluation(jid)
        elif kind == "video":
            import sxs_pipeline; sxs_pipeline.run_auto_eval(jid)
        return (kind, jid, "ok")
    except Exception as e:
        return (kind, jid, f"ERR {str(e)[:120]}")

img = collect("image_jobs")
tts = collect("tts_jobs")
vid = collect("sxs_jobs")
print(f"to re-eval -> image:{len(img)} tts:{len(tts)} video:{len(vid)}  (pairs only)", flush=True)

jobs = [("image", j) for j in img] + [("tts", j) for j in tts] + [("video", j) for j in vid]
t0 = time.time(); done = 0; errs = []
with ThreadPoolExecutor(max_workers=4) as ex:
    futs = [ex.submit(run_one, k, j) for k, j in jobs]
    for f in as_completed(futs):
        kind, jid, status = f.result()
        done += 1
        if status != "ok":
            errs.append((kind, jid, status))
        if done % 10 == 0 or done == len(jobs):
            print(f"  {done}/{len(jobs)} done ({time.time()-t0:.0f}s)", flush=True)

print(f"DONE {done}/{len(jobs)} in {time.time()-t0:.0f}s; errors={len(errs)}", flush=True)
for e in errs[:20]:
    print("  ERR", e, flush=True)
