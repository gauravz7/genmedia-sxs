import os
import json
from google.cloud import firestore

def normalize_gcs_url(url: str) -> str:
    if url and ("X-Goog-Signature" in url or "?X-Goog-Algorithm" in url):
        return url.split("?")[0]
    return url

def migrate():
    project_id = os.getenv("GCP_PROJECT_ID", "vital-octagon-19612")
    db = firestore.Client(project=project_id)
    print("Migrating jobs...")
    if os.path.exists("eval_jobs.json"):
        with open("eval_jobs.json", "r") as f:
            jobs = json.load(f)
            for k, v in jobs.items():
                if v.get('category') and not v.get('categories'):
                    v['categories'] = [v['category']]
                # Normalized URLs
                for var_url_key in ["start_image_url", "end_image_url", "reference_image_url"]:
                    if v.get(var_url_key):
                        v[var_url_key] = normalize_gcs_url(v[var_url_key])
                if v.get("reference_images"):
                    v["reference_images"] = [normalize_gcs_url(u) for u in v["reference_images"]]
                for mid, res in v.get("results", {}).items():
                    if "url" in res:
                        res["url"] = normalize_gcs_url(res["url"])
                    if "result" in res and isinstance(res["result"], dict) and "url" in res["result"]:
                        res["result"]["url"] = normalize_gcs_url(res["result"]["url"])
                db.collection("eval_jobs").document(k).set(v)

    print("Migrating votes...")
    if os.path.exists("votes.json"):
        with open("votes.json", "r") as f:
            votes = json.load(f)
            for v in votes:
                db.collection("votes").document(v["id"]).set(v)

    print("Migrating prompts...")
    if os.path.exists("prompts.json"):
        with open("prompts.json", "r") as f:
            prompts = json.load(f)
            for k, v in prompts.items():
                if v.get('category') and not v.get('categories'):
                    v['categories'] = [v['category']]
                db.collection("prompts").document(k).set(v)
    
    print("Done")

if __name__ == "__main__":
    migrate()
