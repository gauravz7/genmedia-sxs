"""Purge the IP-tainted mihoyo image jobs: back up docs, delete their GCS images,
delete the Firestore docs, and delete any votes referencing them."""
import json
import sys
import time

sys.path.insert(0, ".")
from image_pipeline import (
    _get_firestore_client, IMAGE_COLLECTION, IMAGE_VOTES_COLLECTION,
)
from util.gcs_utils import https_to_gs, get_upload_client

db = _get_firestore_client()
gcs = get_upload_client()


def _urls(job):
    out = []
    for lbl in ("A", "B"):
        r = (job.get("results") or {}).get(lbl) or {}
        for u in (r.get("url"), (r.get("result") or {}).get("url")):
            if u and u not in out:
                out.append(u)
    return out


def _del_blob(url):
    gs = https_to_gs(url)
    if not gs.startswith("gs://"):
        return False
    parts = gs.replace("gs://", "").split("/")
    bucket, blob = parts[0], "/".join(parts[1:])
    try:
        gcs.bucket(bucket).blob(blob).delete()
        return True
    except Exception as e:
        print(f"    blob delete failed ({blob}): {e}")
        return False


docs = list(db.collection(IMAGE_COLLECTION).where("customer", "==", "mihoyo").stream())
backup = [d.to_dict() for d in docs]
json.dump(backup, open(f"mihoyo_jobs_backup_{int(time.time())}.json", "w"),
          ensure_ascii=False, indent=2, default=str)
print(f"Backed up {len(backup)} mihoyo docs.")

job_ids = set()
blobs_deleted = 0
for d in docs:
    j = d.to_dict()
    job_ids.add(j.get("id") or d.id)
    for u in _urls(j):
        if _del_blob(u):
            blobs_deleted += 1
    d.reference.delete()
print(f"Deleted {len(docs)} job docs, {blobs_deleted} GCS images.")

# Purge any votes tied to those jobs.
votes_deleted = 0
for v in db.collection(IMAGE_VOTES_COLLECTION).stream():
    vd = v.to_dict()
    if vd.get("job_id") in job_ids:
        v.reference.delete()
        votes_deleted += 1
print(f"Deleted {votes_deleted} votes referencing purged jobs.")

# Verify nothing remains.
remaining = len(list(db.collection(IMAGE_COLLECTION).where("customer", "==", "mihoyo").stream()))
print(f"Remaining customer==mihoyo docs: {remaining}")
