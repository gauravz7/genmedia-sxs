import os
from google.cloud import firestore

project_id = os.environ.get("GCP_PROJECT_ID", "vital-octagon-19612")
db = firestore.Client(project=project_id)

collections_to_clear = ["prompts", "eval_jobs", "votes"]

for coll in collections_to_clear:
    print(f"Clearing collection: {coll}")
    docs = db.collection(coll).stream()
    count = 0
    for doc in docs:
        doc.reference.delete()
        count += 1
    print(f"Deleted {count} documents from {coll}.")

print("All history cleared successfully.")
