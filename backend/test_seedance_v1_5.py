import requests
import json
import time
import os
from PIL import Image

BACKEND_URL = "http://localhost:8010"

def test_seedance_v1_5():
    print("--- Testing Seedance v1.5 Pro (T2V and I2V) ---")
    
    # 1. Upload a dummy image for I2V
    dummy_img = "seedance_test_upload.png"
    img = Image.new('RGB', (512, 512), color=(100, 100, 200))
    img.save(dummy_img)

    print(f"Uploading {dummy_img} for I2V test...")
    with open(dummy_img, "rb") as f:
        files = {"file": (dummy_img, f, "image/png")}
        resp = requests.post(f"{BACKEND_URL}/api/upload", files=files)
        upload_data = resp.json()
        
    if upload_data.get("status") == "success":
        gcs_url = upload_data["raw_url"]
        print(f"✅ Uploaded to GCS: {gcs_url}")
    else:
        print(f"❌ Upload failed: {upload_data}")
        return

    # 2. Trigger T2V generation
    t2v_model = "seedance-1-5-t2v"
    print(f"Triggering T2V generation for model: {t2v_model}...")
    
    t2v_payload = {
        "text": "A majestic dragon flying over a sunset ocean, cinematic, high detail, 4k.",
        "model_ids": [t2v_model],
        "category": "Cinematic"
    }
    
    t2v_resp = requests.post(f"{BACKEND_URL}/api/generate", json=t2v_payload)
    t2v_data = t2v_resp.json()
    
    if "job_id" in t2v_data:
        t2v_job_id = t2v_data["job_id"]
        print(f"✅ Triggered T2V. Job ID: {t2v_job_id}")
    else:
        print(f"❌ T2V trigger failed: {t2v_data}")
        return

    # 3. Trigger I2V generation
    i2v_model = "seedance-1-5"
    print(f"Triggering I2V generation for model: {i2v_model}...")
    
    i2v_payload = {
        "text": "The dragon starts breathing fire, dramatic motion.",
        "start_image_url": gcs_url,
        "model_ids": [i2v_model],
        "category": "Cinematic"
    }
    
    i2v_resp = requests.post(f"{BACKEND_URL}/api/generate", json=i2v_payload)
    i2v_data = i2v_resp.json()
    
    if "job_id" in i2v_data:
        i2v_job_id = i2v_data["job_id"]
        print(f"✅ Triggered I2V. Job ID: {i2v_job_id}")
    else:
        print(f"❌ I2V trigger failed: {i2v_data}")
        return

    # 4. Poll for both results
    job_ids = [t2v_job_id, i2v_job_id]
    print(f"Polling for jobs {job_ids} (max 15 mins)...")
    
    completed_jobs = set()
    for _ in range(30): # 30 * 30s = 15 mins
        time.sleep(30)
        jobs_resp = requests.get(f"{BACKEND_URL}/api/admin/jobs")
        all_jobs = jobs_resp.json()
        
        for jid in job_ids:
            if jid in completed_jobs:
                continue
                
            job = next((j for j in all_jobs if j["id"] == jid), None)
            if not job:
                continue
                
            results = job.get("results", {})
            model_id = list(results.keys())[0] if results else None
            if not model_id:
                continue
                
            res = results[model_id]
            status = res.get("status")
            
            if status != "generating":
                print(f"--- Result for Job {jid} ({model_id}) ---")
                print(f"Status: {status}, Latency: {res.get('latency')}s")
                if status == "error":
                    print(f"Error: {res.get('error')}")
                else:
                    print(f"URL: {res.get('url')}")
                completed_jobs.add(jid)
        
        if len(completed_jobs) == len(job_ids):
            print("✅ All tests completed.")
            break
    else:
        print("Timed out waiting for generation.")

    # Cleanup
    if os.path.exists(dummy_img):
        os.remove(dummy_img)

if __name__ == "__main__":
    test_seedance_v1_5()
