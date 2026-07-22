"""Import the Dashtoon v2v-x3 STD-vs-Omni pairs into our SxS portal WITHOUT
regenerating: rehost the existing source + rendered output videos to our GCS and
write pre-populated sxs_jobs docs (results already 'success'). Tagged by the
report's category so they flow into the arena + by-tag analytics."""
import json, re, time
import requests

from util.gcs_utils import upload_from_bytes
from sxs_pipeline import _get_firestore_client, EVAL_COLLECTION, _slug

PAIRS = json.load(open("/tmp/v2v_pairs.json"))
DEST_PREFIX = "sxs/v2v-bench"
CUSTOMER = "v2v_edit_bench"

_uploaded: dict = {}  # source url -> gcs url (dedupe repeats)

def rehost(url: str, name: str) -> str:
    if url in _uploaded:
        return _uploaded[url]
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    gcs = upload_from_bytes(r.content, f"{DEST_PREFIX}/{name}.mp4", content_type="video/mp4")
    _uploaded[url] = gcs
    return gcs

db = _get_firestore_client()
written = 0
for p in PAIRS:
    cid = p["cid"]; slug = _slug(cid)
    try:
        src_gcs = rehost(p["source"], f"{slug}__source") if p.get("source") else None
        std_gcs = rehost(p["std_url"], f"{slug}__seedance_std")
        omni_gcs = rehost(p["omni_url"], f"{slug}__omni")
    except Exception as e:
        print(f"SKIP {cid}: rehost failed: {e}")
        continue

    job_id = f"sxs_{slug}_{int(time.time()*1000)}"
    doc = {
        "id": job_id,
        "source": "sxs_auto",
        "batch_id": "v2v_bench_dashtoon_x3",
        "customer": CUSTOMER,
        "prompt_id": cid,
        "prompt": p["prompt"],
        "ratio": "16:9",
        "modality": "v2v",
        "duration": None,
        "categories": [p["category"]] + (["Audio"] if p.get("audio") else []),
        "reference_images": [],
        "reference_videos": [src_gcs] if src_gcs else [],
        "timestamp": time.time(),
        "results": {
            "seedance-2.0-std": {
                "status": "success", "model": "Seedance 2.0",
                "url": std_gcs, "result": {"url": std_gcs},
                "latency": p.get("std_lat"),
            },
            "omni-flash": {
                "status": "success", "model": "Omni Flash",
                "url": omni_gcs, "result": {"url": omni_gcs},
            },
        },
        "auto_eval_status": "skipped",
        "imported_from": "dashtoon v2v-x3 report",
    }
    db.collection(EVAL_COLLECTION).document(job_id).set(doc)
    written += 1
    print(f"OK {cid}  [{p['category']}]{'  +audio' if p.get('audio') else ''}")

print(f"\nDONE: wrote {written}/{len(PAIRS)} jobs; rehosted {len(_uploaded)} videos.")
