"""Backfill `categories` for TTS/voice jobs that have none: LANGUAGE tag(s) (from
the stored language code, or detected from the text) + INDUSTRY tag(s) from the
curated list. Same shared `categories` field used by human eval, AI evals, and
analytics. Idempotent: only touches jobs with empty categories unless --all.

Run: python3 retag_tts.py [--all]
"""
import asyncio
import sys

from google.cloud import firestore

from tts_pipeline import (
    TTS_COLLECTION,
    _detect_language,
    _voice_categories,
)

CONCURRENCY = 5


def _client():
    return firestore.Client(project="vital-octagon-19612")


async def main():
    force = "--all" in sys.argv
    db = _client()
    targets = []
    for d in db.collection(TTS_COLLECTION).stream():
        x = d.to_dict() or {}
        if not force and (x.get("categories") or []):
            continue
        text = (x.get("text") or x.get("prompt") or "").strip()
        if text:
            targets.append((d.id, text, (x.get("language") or "").strip()))
    print(f"[retag-tts] {len(targets)} voice docs to tag (force={force})", flush=True)

    sem = asyncio.Semaphore(CONCURRENCY)
    done = {"n": 0, "ok": 0}

    async def run(jid, text, lang):
        async with sem:
            tags = []
            try:
                # _detect_language / _classify_industry are sync gemini calls;
                # offload to a thread so the semaphore actually parallelizes.
                def _work():
                    code = lang or _detect_language(text)
                    return _voice_categories(text, code)
                tags = await asyncio.to_thread(_work)
            except Exception as e:
                print(f"[retag-tts] error {jid}: {e}", flush=True)
            if tags:
                _client().collection(TTS_COLLECTION).document(jid).update({"categories": tags})
                done["ok"] += 1
            done["n"] += 1
            if done["n"] % 20 == 0:
                print(f"[retag-tts] {done['n']}/{len(targets)} (tagged {done['ok']})", flush=True)

    await asyncio.gather(*[run(*t) for t in targets])
    print(f"[retag-tts] COMPLETE processed={done['n']} tagged={done['ok']}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
