import requests
import json
import time

BACKEND_URL = "http://localhost:8010"

def test_async_generation():
    print("--- Testing Asynchronous Generation (Non-blocking) ---")
    
    prompts = [
        "A cute cat playing with a red ball in a garden.",
        "A futuristic city with flying cars and neon lights.",
        "A calm mountain lake at sunrise with reflections."
    ]
    
    job_ids = []
    
    start_time = time.time()
    for i, prompt in enumerate(prompts):
        print(f"Submitting prompt {i+1}: {prompt}")
        payload = {
            "text": prompt,
            "model_ids": ["seedance-1-5-t2v"],
            "category": "Test"
        }
        resp = requests.post(f"{BACKEND_URL}/api/generate", json=payload)
        data = resp.json()
        
        if "job_id" in data:
            jid = data["job_id"]
            print(f"✅ Received Job ID {jid} immediately. Status: {data.get('status')}")
            job_ids.append(jid)
        else:
            print(f"❌ Submission failed: {data}")
            return

    end_time = time.time()
    duration = end_time - start_time
    print(f"\nTotal submission time for {len(prompts)} prompts: {duration:.2f}s")
    
    if duration < 5: # Expecting immediate responses
        print("✅ SUCCESS: Submissions were non-blocking.")
    else:
        print("❌ FAILURE: Submissions took too long, might be blocking.")

    print("\nPolling for job statuses in Admin Jobs...")
    for _ in range(10):
        time.sleep(10)
        jobs_resp = requests.get(f"{BACKEND_URL}/api/admin/jobs")
        all_jobs = jobs_resp.json()
        
        found_all = True
        for jid in job_ids:
            job = next((j for j in all_jobs if j["id"] == jid), None)
            if not job:
                print(f"Job {jid} not found in registry yet.")
                found_all = False
                continue
            
            # Check results
            results = job.get("results", {})
            statuses = [res.get("status") for res in results.values()]
            print(f"Job {jid} status: {statuses}")
            
            if "generating" in statuses:
                found_all = False
        
        if found_all:
            print("✅ All background jobs have moved past 'generating' status.")
            break
    else:
        print("Still waiting for some jobs to complete background processing.")

if __name__ == "__main__":
    test_async_generation()
