"""Resume a stalled image batch: re-run ONLY missing/failed sides (reusing any
side already 'success', so no duplicate FAL cost), and patch the old
instant-ramen side to gemini-3.1-flash-lite-image first.

Run: python3 resume_batch.py <batch_id>
"""
import asyncio
import sys

import image_pipeline as ip

BATCH = sys.argv[1] if len(sys.argv) > 1 else "imgbatch_1782733668"
NEW_GEMINI = "gemini-3.1-flash-lite-image"
JOB_CONCURRENCY = 3


def _patch_and_collect():
    db = ip._get_firestore_client()
    jobs = []
    patched = 0
    for d in db.collection("image_jobs").where("batch_id", "==", BATCH).stream():
        x = d.to_dict()
        if x.get("auto_eval_status") == "done":
            continue
        ss = x.get("side_specs") or {}
        sm = x.get("side_map") or {}
        changed = False
        for label in ("A", "B"):
            spec = ss.get(label) or {}
            if spec.get("model") == "instant-ramen" or sm.get(label) == "instant-ramen":
                ss[label] = {"engine": NEW_GEMINI, "provider": "gemini", "model": NEW_GEMINI, "quality": None}
                sm[label] = NEW_GEMINI
                changed = True
        if changed:
            db.collection("image_jobs").document(d.id).update({"side_specs": ss, "side_map": sm})
            patched += 1
        jobs.append(d.id)
    return jobs, patched


async def main():
    jobs, patched = _patch_and_collect()
    print(f"[resume] batch={BATCH} non-done={len(jobs)} patched_instant_ramen={patched}", flush=True)
    sem = asyncio.Semaphore(JOB_CONCURRENCY)
    done = {"n": 0}

    async def run(jid):
        async with sem:
            try:
                await ip.retry_job(jid)
            except Exception as e:
                print(f"[resume] error {jid}: {e}", flush=True)
            done["n"] += 1
            if done["n"] % 25 == 0:
                print(f"[resume] processed {done['n']}/{len(jobs)}", flush=True)

    await asyncio.gather(*[run(j) for j in jobs])
    print(f"[resume] COMPLETE processed={done['n']}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
