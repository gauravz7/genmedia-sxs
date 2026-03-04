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

print("Fetching eval_jobs from Firestore...")
docs = list(db.collection("eval_jobs").stream())
print(f"Found {len(docs)} jobs to check.")

updated_count = 0
deleted_count = 0

for doc in docs:
    job = doc.to_dict()
    changed = False
    results = job.get("results", {})
    
    for mid, res in results.items():
        if res.get("status") == "success":
            url = extract_url(res)
            if not url:
                print(f"[{doc.id}] {mid}: No URL found. Marking as error.")
                res["status"] = "error"
                res["error_message"] = "No URL found"
                changed = True
                continue
                
            try:
                # print(f"Checking {url}")
                r = requests.head(url, timeout=5)
                # Some signed URLs might reject HEAD but allow GET
                if r.status_code >= 400:
                    r2 = requests.get(url, stream=True, timeout=5)
                    r2.close()
                    if r2.status_code >= 400:
                        print(f"[{doc.id}] {mid}: Broken URL ({r2.status_code}). Marking as error.")
                        res["status"] = "error"
                        res["error_message"] = f"Broken URL {r2.status_code}"
                        changed = True
            except Exception as e:
                print(f"[{doc.id}] {mid}: Exception ({e}). Marking as error.")
                res["status"] = "error"
                res["error_message"] = str(e)
                changed = True
                
    if changed:
        success_count = sum(1 for r in results.values() if r.get("status") == "success")
        if success_count < 2:
            print(f"-> Job {doc.id} now has {success_count} valid models. DELETING job.")
            db.collection("eval_jobs").document(doc.id).delete()
            deleted_count += 1
        else:
            print(f"-> Job {doc.id} updated with invalidated links.")
            db.collection("eval_jobs").document(doc.id).update({"results": results})
            updated_count += 1

print("-" * 30)
print(f"Scrub complete! Updated {updated_count} jobs. Deleted {deleted_count} jobs.")
