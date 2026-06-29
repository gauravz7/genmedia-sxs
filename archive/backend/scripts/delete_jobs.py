from google.cloud import firestore

jobs_to_delete = [
    "job_1772465362273",
    "job_1772461780692",
    "job_1772461958791",
    "job_1772465332225",
    "BATCH_002"
]

db = firestore.Client(project="vital-octagon-19612")

for job_id in jobs_to_delete:
    print(f"Deleting {job_id}...")
    db.collection("eval_jobs").document(job_id).delete()

print("Done deleting specified jobs.")
