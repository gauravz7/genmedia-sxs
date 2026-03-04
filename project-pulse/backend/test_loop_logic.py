import json
import time

# emulate in-memory loading
with open('eval_jobs.json') as f:
    jobs = json.load(f)

# The keys we want to check for being broken 
# Only 4 specific models were okay across all tests:
allowed_ok = [
    "veo-3-1-fast-preview-t2v",
    "veo-3-1-fast-001-i2v",
    "veo-3-1-001-i2v",
    "kling-2-6-i2v",
    "seedance-1-fast-i2v"
]

st = time.time()
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

print(f"Loaded {len(jobs)} jobs")

st = time.time()

for _ in range(5):
    all_jobs = list(jobs.values())
    suitable_jobs = []
    
    for j in all_jobs:
        success_models = [mid for mid, res in j.get('results', {}).items() if res.get("status") == "success"]
        if len(success_models) >= 2:
            suitable_jobs.append((j, success_models))
            
    import random
    job, success_models = random.choice(suitable_jobs)
    pair = random.sample(success_models, 2)
    side_a_model = pair[0]
    side_b_model = pair[1]
    
    url_a = extract_url(job['results'][side_a_model])
    url_b = extract_url(job['results'][side_b_model])
             
    start_image_url=get_signed_url(job.get('start_image_url')) if job.get('start_image_url') else None
    end_image_url=get_signed_url(job.get('end_image_url')) if job.get('end_image_url') else None
    reference_image_url=get_signed_url(job.get('reference_image_url')) if job.get('reference_image_url') else None
    reference_images=[get_signed_url(u) for u in job.get('reference_images', [])] if job.get('reference_images') else None

print(f"Finished 5 iterations over dictionary in {time.time()-st:.4f}s")
