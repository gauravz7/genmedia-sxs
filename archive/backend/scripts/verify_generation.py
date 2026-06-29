import requests
import json
import time

BASE_URL = "http://localhost:8010/api"

def test_prompt_registration():
    print("--- Testing Prompt Registration ---")
    payload = {
        "text": "A beautiful cinematic shot of a mountain range at sunset, 8k resolution.",
        "category": "Beauty",
        "start_image_url": "https://storage.googleapis.com/project-pulse-assets/test-start.png",
        "end_image_url": "https://storage.googleapis.com/project-pulse-assets/test-end.png"
    }
    resp = requests.post(f"{BASE_URL}/admin/prompts", json=payload)
    if resp.status_code == 200:
        data = resp.json()
        print(f"✅ Registered prompt: {data['prompt']['id']}")
        return data['prompt']['id']
    else:
        print(f"❌ Failed to register prompt: {resp.text}")
        return None

def test_generation(prompt_id, prompt_text):
    print("\n--- Testing Generation with Metadata ---")
    payload = {
        "text": prompt_text,
        "category": "Beauty",
        "prompt_id": prompt_id,
        "model_ids": ["kling", "seedance"] # Testing with FAL models for GCS upload check
    }
    resp = requests.post(f"{BASE_URL}/generate", json=payload)
    if resp.status_code == 200:
        data = resp.json()
        print(f"✅ Triggered generation. Job ID: {data['job_id']}")
        print(f"Initiation Time: {data['initiation_time']}")
        for model_id, res in data["results"].items():
            print(f"Model: {model_id}, Status: {res.get('status')}, Latency: {res.get('latency')}s")
            if res.get("status") == "success":
                print(f"  URL: {res['result']['video']['url']}")
        return data['job_id']
    else:
        print(f"❌ Generation failed: {resp.text}")
        return None

def verify_persistence(job_id):
    print("\n--- Verifying Persistence in eval_jobs.json ---")
    try:
        with open("eval_jobs.json", "r") as f:
            jobs = json.load(f)
            if job_id in jobs:
                job = jobs[job_id]
                print(f"✅ Job {job_id} found in eval_jobs.json")
                print(f"Initiation Time recorded: {job.get('initiation_time')}")
                print(f"Prompt ID recorded: {job.get('prompt_id')}")
            else:
                print(f"❌ Job {job_id} NOT found in eval_jobs.json")
    except Exception as e:
        print(f"❌ Error reading eval_jobs.json: {e}")

def test_r2v_registration():
    print("\n--- Testing R2V Prompt Registration ---")
    payload = {
        "text": "The subject character walking through a futuristic neon city.",
        "category": "Animation",
        "reference_images": [
            "https://storage.googleapis.com/project-pulse-assets/ref1.png",
            "https://storage.googleapis.com/project-pulse-assets/ref2.png"
        ]
    }
    resp = requests.post(f"{BASE_URL}/admin/prompts", json=payload)
    if resp.status_code == 200:
        data = resp.json()
        print(f"✅ Registered R2V prompt: {data['prompt']['id']}")
        return data['prompt']['id']
    else:
        print(f"❌ Failed to register R2V prompt: {resp.text}")
        return None

if __name__ == "__main__":
    # Note: Ensure the backend is running before executing this
    try:
        # Test I2V/T2V path
        pid = test_prompt_registration()
        if pid:
            jid = test_generation(pid, "A beautiful cinematic shot of a mountain range at sunset, 8k resolution.")
            if jid:
                verify_persistence(jid)
        
        # Test R2V path
        r2v_pid = test_r2v_registration()
        if r2v_pid:
            print("\n--- Testing R2V Generation Trigger ---")
            payload = {
                "text": "The subject character walking through a futuristic neon city.",
                "category": "Animation",
                "prompt_id": r2v_pid,
                "reference_images": [
                    "https://storage.googleapis.com/project-pulse-assets/ref1.png",
                    "https://storage.googleapis.com/project-pulse-assets/ref2.png"
                ],
                "model_ids": ["seedance"] # Testing R2V on Seedance (it uses structure references)
            }
            resp = requests.post(f"{BASE_URL}/generate", json=payload)
            if resp.status_code == 200:
                data = resp.json()
                print(f"✅ Triggered R2V generation. Job ID: {data['job_id']}")
                verify_persistence(data['job_id'])
            else:
                print(f"❌ R2V Generation failed: {resp.text}")

    except requests.exceptions.ConnectionError:
        print("❌ Error: Backend is not running on http://localhost:8010")
