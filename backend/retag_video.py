"""Redo tags for all video prompts/pairs: regenerate `categories` from each
prompt via Gemini and overwrite. Covers sxs_jobs (the eval pairs) + eval_jobs.

Run: python3 retag_video.py
"""
import asyncio

from google.cloud import firestore

from providers.vertex_provider import generate_tags_with_gemini

COLLECTIONS = ["sxs_jobs", "eval_jobs"]
CONCURRENCY = 5


def _client():
    return firestore.Client(project="vital-octagon-19612")


async def main():
    db = _client()
    targets = []
    for coll in COLLECTIONS:
        for d in db.collection(coll).stream():
            x = d.to_dict() or {}
            prompt = (x.get("prompt") or x.get("text") or "").strip()
            if prompt:
                targets.append((coll, d.id, prompt, x.get("start_image_url"),
                                x.get("end_image_url"), x.get("reference_images")))
    print(f"[retag] {len(targets)} video docs to re-tag", flush=True)

    sem = asyncio.Semaphore(CONCURRENCY)
    done = {"n": 0, "ok": 0}

    async def run(coll, jid, prompt, s_img, e_img, refs):
        async with sem:
            try:
                tags = await generate_tags_with_gemini(prompt, s_img, e_img, refs)
                if tags:
                    _client().collection(coll).document(jid).update({"categories": tags})
                    done["ok"] += 1
            except Exception as e:
                print(f"[retag] error {coll}/{jid}: {e}", flush=True)
            done["n"] += 1
            if done["n"] % 20 == 0:
                print(f"[retag] {done['n']}/{len(targets)} (tagged {done['ok']})", flush=True)

    await asyncio.gather(*[run(*t) for t in targets])
    print(f"[retag] COMPLETE processed={done['n']} tagged={done['ok']}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
