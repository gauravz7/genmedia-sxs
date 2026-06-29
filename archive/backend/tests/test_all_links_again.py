import requests
from google.cloud import firestore
from util.gcs_utils import get_signed_url
import os

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

for doc in docs:
    job = doc.to_dict()
    results = job.get("results", {})
    success_count = 0
    
    for mid, res in results.items():
        if res.get("status") == "success":
            url = extract_url(res)
            try:
                # the browser uses GET, let's test GET
                r = requests.get(url, stream=True, timeout=5)
                # Read 1 byte to ensure it's actually streaming data
                chunk = next(r.iter_content(chunk_size=1), b'')
                r.close()
                if r.status_code >= 400:
                    print(f"BROKEN! [{doc.id}] {mid}: status {r.status_code}, url: {url[:100]}")
                else:
                    print(f"OK: [{doc.id}] {mid}")
                    success_count += 1
            except Exception as e:
                print(f"EXCEPTION! [{doc.id}] {mid}: {e}")
                
    if success_count < 2:
        print(f"-> Job {doc.id} now has only {success_count} valid models. THIS WOULD FAIL PAIRING!")

