"""Backfill `categories` for image jobs that have none, from the prompt (+ input
image) via Gemini. Same shared `categories` field used by human eval, AI evals,
and analytics. Idempotent: only touches jobs with empty categories unless --all.

Run: python3 retag_image.py [--all]
"""
import asyncio
import sys

from google.cloud import firestore

from providers.vertex_provider import generate_tags_with_gemini

IMAGE_COLLECTION = "image_jobs"
CONCURRENCY = 5


def _client():
    return firestore.Client(project="vital-octagon-19612")


async def main():
    force = "--all" in sys.argv
    db = _client()
    targets = []
    for d in db.collection(IMAGE_COLLECTION).stream():
        x = d.to_dict() or {}
        if not force and (x.get("categories") or []):
            continue
        prompt = (x.get("prompt") or "").strip()
        if prompt or x.get("input_image"):
            targets.append((d.id, prompt, x.get("input_image") or None))
    print(f"[retag-image] {len(targets)} image docs to tag (force={force})", flush=True)

    sem = asyncio.Semaphore(CONCURRENCY)
    done = {"n": 0, "ok": 0}

    async def run(jid, prompt, in_img):
        async with sem:
            tags = None
            try:
                tags = await generate_tags_with_gemini(prompt, in_img)
                if not tags:  # invalid image -> [] -> retry text-only
                    tags = await generate_tags_with_gemini(prompt)
            except Exception as e:
                print(f"[retag-image] error {jid}: {e}", flush=True)
            if tags:
                _client().collection(IMAGE_COLLECTION).document(jid).update({"categories": tags})
                done["ok"] += 1
            done["n"] += 1
            if done["n"] % 20 == 0:
                print(f"[retag-image] {done['n']}/{len(targets)} (tagged {done['ok']})", flush=True)

    await asyncio.gather(*[run(*t) for t in targets])
    print(f"[retag-image] COMPLETE processed={done['n']} tagged={done['ok']}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
