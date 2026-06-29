
import requests
import json
import time
import os

BACKEND_URL = "http://localhost:8010"

def test_admin_seedance_flow():
    print("--- Testing Admin Seedance 1.0 Lite & Upload Flow ---")
    
    # 1. Create a valid image for upload testing (64x64 to avoid Vertex dimension errors)
    dummy_img = "test_upload.png"
    from PIL import Image
    import io
    img = Image.new('RGB', (64, 64), color=(73, 109, 137))
    img.save(dummy_img)

    # 2. Upload the dummy image
    print(f"Uploading {dummy_img}...")
    with open(dummy_img, "rb") as f:
        files = {"file": (dummy_img, f, "image/png")}
        resp = requests.post(f"{BACKEND_URL}/api/upload", files=files)
        upload_data = resp.json()
        
    if upload_data.get("status") == "success":
        gcs_url = upload_data["url"]
        print(f"✅ Uploaded to GCS: {gcs_url}")
    else:
        print(f"❌ Upload failed: {upload_data}")
        return

    # 3. Trigger generation for Seedance 1.0 Lite and Veo 3.1
    models = ["seedance-1-0-lite", "veo-3-1"]
    print(f"Triggering generation for models: {models}...")
    
    payload = {
        "text": "A small dog running in a sunny garden, highly detailed, 4k.",
        "start_image_url": gcs_url,
        "models": models,
        "category": "Animation"
    }
    
    gen_resp = requests.post(f"{BACKEND_URL}/api/generate", json=payload)
    gen_data = gen_resp.json()
    
    if "job_id" in gen_data:
        job_id = gen_data["job_id"]
        print(f"✅ Triggered generation. Job ID: {job_id}")
    else:
        print(f"❌ Generation trigger failed: {gen_data}")
        return

    # 4. Wait and Poll for results
    print("Polling for results (max 10 mins)...")
    for _ in range(20):
        time.sleep(30)
        jobs_resp = requests.get(f"{BACKEND_URL}/api/admin/jobs")
        jobs = jobs_resp.json()
        
        job = next((j for j in jobs if j["id"] == job_id), None)
        if not job:
            continue
            
        results = job.get("results", {})
        all_done = True
        for m in models:
            m_res = results.get(m, {})
            status = m_res.get("status")
            if status == "generating":
                all_done = False
                break
        
        if all_done:
            print(f"--- Results for Job {job_id} ---")
            for m in models:
                m_res = results.get(m, {})
                status = m_res.get("status")
                url = m_res.get("url")
                print(f"Model: {m}, Status: {status}, Latency: {m_res.get('latency')}s")
                if status == "error":
                    print(f"  Error: {m_res.get('error')}")
                else:
                    print(f"  URL: {url}")
            break
    else:
        print("Timed out waiting for generation.")

    # Cleanup
    if os.path.exists(dummy_img):
        os.remove(dummy_img)

if __name__ == "__main__":
    test_admin_seedance_flow()
