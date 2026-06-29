
import requests
import json
import time

BACKEND_URL = "http://localhost:8010"

def test_hippo_interpolation():
    print("--- Testing Hippo Interpolation Scenario ---")

    # 1. Generate Start Frame
    print("Generating Start Frame: Hippo on riverbank...")
    start_prompt = "A hyper-realistic photo of a large hippo standing on a riverbank, cinematic lighting, 8k"
    resp = requests.post(f"{BACKEND_URL}/api/generate-image", json={"prompt": start_prompt, "ratio": "16:9"})
    start_data = resp.json()
    if start_data.get("status") != "success":
        print(f"❌ Failed to generate start frame: {start_data}")
        return
    start_image_url = start_data["url"]
    print(f"✅ Start Frame: {start_image_url}")

    # 2. Generate End Frame
    print("Generating End Frame: Hippo submerged...")
    end_prompt = "A hyper-realistic photo of the same hippo submerged in the river with only its eyes and ears visible, water ripples, cinematic lighting, 8k"
    resp = requests.post(f"{BACKEND_URL}/api/generate-image", json={"prompt": end_prompt, "ratio": "16:9"})
    end_data = resp.json()
    if end_data.get("status") != "success":
        print(f"❌ Failed to generate end frame: {end_data}")
        return
    end_image_url = end_data["url"]
    print(f"✅ End Frame: {end_image_url}")

    # 3. Trigger I2V Interpolation
    models = ["seedance-1-5", "veo-3-1"]
    print(f"Triggering I2V Interpolation for models: {models}...")
    
    payload = {
        "text": "Add motion : Hippo takes a dip in the water",
        "start_image_url": start_image_url,
        "end_image_url": end_image_url,
        "models": models,
        "category": "Nature"
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
    start_time = time.time()
    for _ in range(30):
        time.sleep(20)
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
        
        elapsed = time.time() - start_time
        if elapsed > 600:
            print("Timed out waiting for generation.")
            break
    else:
        print("Polling ended.")

if __name__ == "__main__":
    test_hippo_interpolation()
