import json

with open("eval_jobs.json") as f:
    jobs = json.load(f)

# Hard reset the broken urls again
allowed_ok = [
    "veo-3-1-fast-preview-t2v",
    "kling-2-6-i2v",
    "seedance-1-fast-i2v",
    "veo-3-1-fast-001-t2v",
    "kling-2-5-t2v"
]

for j_id, job in jobs.items():
    res = job.get('results', {})
    for mid in list(res.keys()):
        if res[mid].get("status") == "success" and mid not in allowed_ok:
            res[mid]["status"] = "error"

with open("eval_jobs.json", "w") as f:
    json.dump(jobs, f, indent=2)

print("eval_jobs fixed harder")
