"""One-off runner: submit anime_image_cases.json through the image SxS pipeline
locally (mirrors the /api/image/upload route, minus HTTP/auth)."""
import asyncio
import json
import sys
import time

from image_pipeline import create_image_job, process_batch

CASES_FILE = sys.argv[1] if len(sys.argv) > 1 else "anime_image_cases.json"


async def main():
    data = json.load(open(CASES_FILE))
    cases = data.get("cases", data) if isinstance(data, dict) else data
    batch_id = f"imgbatch_anime_{int(time.time())}"
    pairs = [(create_image_job(c, batch_id=batch_id), c) for c in cases]
    print(f"BATCH_ID={batch_id}")
    print(f"QUEUED={len(pairs)} jobs")
    for jid, c in pairs:
        print(f"  {jid}  <-  {c['id']}")
    sys.stdout.flush()
    t0 = time.time()
    await process_batch(pairs)
    print(f"DONE in {time.time()-t0:.1f}s  batch_id={batch_id}")


if __name__ == "__main__":
    asyncio.run(main())
