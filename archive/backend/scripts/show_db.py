import os
import json
from google.cloud import firestore

project_id = os.environ.get("GCP_PROJECT_ID", "vital-octagon-19612")
db = firestore.Client(project=project_id)

def show_collection(coll_name):
    print(f"\n{'='*40}")
    print(f"COLLECTION: {coll_name}")
    print(f"{'='*40}")
    docs = list(db.collection(coll_name).stream())
    if not docs:
        print(" (Empty collection)")
    for doc in docs:
        print(f"\n--- Document ID: {doc.id} ---")
        try:
            print(json.dumps(doc.to_dict(), indent=2, default=str))
        except Exception as e:
            print(f"Error printing document: {e}")
            print(doc.to_dict())

show_collection("prompts")
show_collection("eval_jobs")
show_collection("votes")
