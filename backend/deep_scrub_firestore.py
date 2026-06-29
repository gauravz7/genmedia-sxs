import os
import requests
from google.cloud import firestore
from util.gcs_utils import get_signed_url

# Initialize firestore
project_id = os.environ.get("GCP_PROJECT_ID", "vital-octagon-19612")
db = firestore.Client(project=project_id)

def extract_url(res):
    url = None
    if "url" in res:
        url = res["url"]
    elif "result" in res and isinstance(res["result"], dict):
        if "url" in res["result"]:
            url = res["result"]["url"]
        elif "video" in res["result"] and isinstance(res["result"]["video"], dict):
            url = res["result"]["video"].get("url")
        elif "video_url" in res["result"]:
            url = res["result"]["video_url"]
    
    if url and (url.startswith("gs://") or "storage.googleapis.com" in url):
        return get_signed_url(url)
    return url

docs = list(db.collection("eval_jobs").stream())
updated_count = 0
deleted_count = 0

for doc in docs:
    job = doc.to_dict()
    changed = False
    results = job.get("results", {})
    success_count = 0
    
    for mid, res in list(results.items()):
        if res.get("status") == "success":
            url = extract_url(res)
            is_valid = False
            try:
                r = requests.get(url, stream=True, timeout=5)
                # Read 1 chunk to verify stream works
                chunk = next(r.iter_content(chunk_size=1), b'')
                r.close()
                if r.status_code < 400:
                    is_valid = True
                    success_count += 1
            except Exception as e:
                pass
                
            if not is_valid:
                print(f"[{doc.id}] {mid}: Broken video streaming access. Marking as error.")
                res["status"] = "error"
                res["error_message"] = "Broken video access testing GET"
                changed = True
                
    if changed:
        if success_count < 2:
            print(f"-> Job {doc.id} now has {success_count} valid models. DELETING job.")
            db.collection("eval_jobs").document(doc.id).delete()
            deleted_count += 1
        else:
            print(f"-> Job {doc.id} updated with invalidated links.")
            db.collection("eval_jobs").document(doc.id).update({"results": results})
            updated_count += 1

print("-" * 30)
print(f"Deep scrub complete! Updated {updated_count} jobs. Deleted {deleted_count} jobs.")
