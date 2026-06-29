
import os
import requests
from google.cloud import storage
from google.oauth2 import service_account
import datetime

GCP_PROJECT_ID = "vital-octagon-19612"
GCS_BUCKET_NAME = "project-pulse"

def test_signing():
    print("Testing GCS Signing...")
    if not os.path.exists("signing_keys.json"):
        print("Error: signing_keys.json not found")
        return

    creds = service_account.Credentials.from_service_account_file("signing_keys.json")
    client = storage.Client(project=GCP_PROJECT_ID, credentials=creds)
    bucket = client.bucket(GCS_BUCKET_NAME)
    
    blob_name = f"test_sign_{int(datetime.datetime.now().timestamp())}.txt"
    blob = bucket.blob(blob_name)
    
    # Upload something using the signing client (to verify it has perms)
    blob.upload_from_string("test content", content_type="text/plain")
    print(f"Uploaded {blob_name}")
    
    # Sign it
    signed_url = blob.generate_signed_url(
        version="v4",
        expiration=datetime.timedelta(minutes=60),
        method="GET"
    )
    print(f"Generated URL: {signed_url}")
    
    # Try to fetch it
    resp = requests.get(signed_url)
    print(f"Fetch Status: {resp.status_code}")
    if resp.status_code != 200:
        print(f"Error Body: {resp.text}")
    else:
        print("Fetch Success!")

if __name__ == "__main__":
    test_signing()
