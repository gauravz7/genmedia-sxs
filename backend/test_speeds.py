import json
import time
import requests
from util.gcs_utils import get_signed_url

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

with open('eval_jobs.json') as f:
    jobs = json.load(f)

for j_id, job in jobs.items():
    success_models = {mid: res for mid, res in job.get('results', {}).items() if res.get('status') == 'success'}
    if len(success_models) >= 2:
        print(f"Testing URLs for {j_id}")
        for mid, res in success_models.items():
            u = extract_url(res)
            st = time.time()
            if u:
                r = requests.head(u, timeout=3)
                print(f"  {mid}: {r.status_code} ({time.time()-st:.2f}s)")
