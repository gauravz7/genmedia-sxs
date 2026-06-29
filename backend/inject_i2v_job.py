import os
import json
import time
from google.cloud import firestore

project_id = os.environ.get("GCP_PROJECT_ID", "vital-octagon-19612")
db = firestore.Client(project=project_id)

# Fetch a known good job to clone it
docs = list(db.collection("eval_jobs").limit(1).stream())
if docs:
    job = docs[0].to_dict()
    new_job = job.copy()
    new_job["id"] = "job_1772176312273_injected"
    new_job["prompt"] = "Injected I2V prompt for UI testing"
    new_job["categories"] = ["I2V", "Studio Shots"]
    # Provide a virtual-hosted style UI image URL
    new_job["start_image_url"] = "https://project-pulse.storage.googleapis.com/uploads/1772176215_Arush-removebg-preview.jpg"
    new_job["reference_images"] = []
    
    # Just grab any two random success videos to simulate I2V links working
    models_to_inject = []
    
    # Use real URLs from public tests to prevent broken links
    valid_vid1 = "https://storage.googleapis.com/project-pulse/fal_1772176227_ZMn0e_OSyjQ0eqhZnCg_F_output.mp4"
    valid_vid2 = "https://storage.googleapis.com/project-pulse/fal_1772176285_IEth4E7ohMPv1zHtt7cQP_video.mp4"
    
    new_job["results"] = {
        "kling-2-6-i2v": {
            "status": "success",
            "url": valid_vid1
        },
        "veo-3-1-fast-001-i2v": {
            "status": "success",
            "url": valid_vid2
        }
    }
    
    db.collection("eval_jobs").document(new_job["id"]).set(new_job)
    print("Injected I2V testing job.")
