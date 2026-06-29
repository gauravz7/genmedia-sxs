import os
import requests
from google.cloud import storage
from google.oauth2 import service_account
import google.auth

# Load environment variables (assuming they are already loaded in main.py, but good to be safe)
from dotenv import load_dotenv
load_dotenv()

GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "vital-octagon-19612")
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "project-pulse")
SIGNING_KEYS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "signing_keys.json")

import datetime
from typing import Optional

def normalize_gcs_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return url
    if "storage.googleapis.com" in url or url.startswith("gs://"):
        return url.split("?")[0]
    return url

def https_to_gs(url: str) -> str:
    """
    Converts a GCS HTTPS URL (path-style or virtual-hosted) to a gs:// URI.
    Returns the original string if it is not a GCS URL.
    """
    if not url or not isinstance(url, str):
        return url
    
    if url.startswith("gs://"):
        return url.split("?")[0]
        
    if "storage.googleapis.com" not in url:
        return url

    clean_url = url.split("?")[0]
    
    try:
        if ".storage.googleapis.com/" in clean_url:
            # Virtual-hosted: https://bucket.storage.googleapis.com/object
            bucket_name = clean_url.split(".storage.googleapis.com/")[0].replace("https://", "").replace("http://", "")
            blob_name = clean_url.split(".storage.googleapis.com/")[1]
            return f"gs://{bucket_name}/{blob_name}"
        elif "storage.googleapis.com/" in clean_url:
            # Path-style: https://storage.googleapis.com/bucket/object
            parts = clean_url.replace("https://", "").replace("http://", "").replace("storage.googleapis.com/", "").split("/")
            bucket_name = parts[0]
            blob_name = "/".join(parts[1:])
            return f"gs://{bucket_name}/{blob_name}"
    except Exception:
        pass
        
    return url

_UPLOAD_CLIENT = None

def get_upload_client():
    """
    Returns a storage.Client using standard Application Default Credentials (ADC).
    """
    global _UPLOAD_CLIENT
    if _UPLOAD_CLIENT is None:
        _UPLOAD_CLIENT = storage.Client(project=GCP_PROJECT_ID)
    return _UPLOAD_CLIENT

_SIGNING_CREDS = None
_SIGNING_CLIENT = None

def get_signing_credentials():
    """
    Returns service account credentials from JSON for local URL signing.
    Local signing only needs the private key and doesn't require a network refresh.
    """
    global _SIGNING_CREDS
    if _SIGNING_CREDS is not None:
        return _SIGNING_CREDS

    if os.path.exists(SIGNING_KEYS_PATH):
        try:
            _SIGNING_CREDS = service_account.Credentials.from_service_account_file(SIGNING_KEYS_PATH)
            return _SIGNING_CREDS
        except Exception as e:
            print(f"DEBUG: Failed to load signing credentials from {SIGNING_KEYS_PATH}: {e}")
    return None

def get_signed_url(gcs_url_or_uri: str, expiration_minutes: int = 60) -> str:
    """
    Generates a proxy URL instead of a broken V4 Signed URL.
    This routes the UI's requests through the backend where ADC reads the bytes.
    """
    if not gcs_url_or_uri or not isinstance(gcs_url_or_uri, str):
        return gcs_url_or_uri

    import urllib.parse
    
    # If it's already a proxy URL, don't double wrap it
    if "/api/media?url=" in gcs_url_or_uri:
        return gcs_url_or_uri

    # Ensure we use native style for internal backend download_blob_to_bytes
    if gcs_url_or_uri.startswith("https://storage.googleapis.com/") or ".storage.googleapis.com" in gcs_url_or_uri:
        gcs_url_or_uri = https_to_gs(gcs_url_or_uri)
    
    encoded = urllib.parse.quote(gcs_url_or_uri)
    return f"/api/media?url={encoded}"

def upload_from_url(url: str, destination_blob_name: str) -> str:
    """
    Downloads a file from a URL and uploads it to GCS.
    Detects if the source is GCS and uses ADC-backed download if so.
    Returns the public URL or GCS URI.
    """
    client = get_upload_client()
    bucket = client.bucket(GCS_BUCKET_NAME)
    blob = bucket.blob(destination_blob_name)

    # Download from URL
    is_gcs = (url.startswith("gs://") or "storage.googleapis.com" in url)
    
    if is_gcs:
        print(f"DEBUG: Internal GCS transfer for {url}")
        content = download_blob_to_bytes(url)
        content_type = "image/png" # Default for our current workloads
    else:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()
        content = response.content
        content_type = response.headers.get('content-type')

    # Upload to GCS
    blob.upload_from_string(content, content_type=content_type)
    
    return f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{destination_blob_name}"

def upload_from_path(local_path: str, destination_blob_name: str) -> str:
    """
    Uploads a local file to GCS.
    """
    client = get_upload_client()
    bucket = client.bucket(GCS_BUCKET_NAME)
    blob = bucket.blob(destination_blob_name)

    blob.upload_from_filename(local_path)
    
    return f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{destination_blob_name}"

def upload_from_bytes(data: bytes, destination_blob_name: str, content_type: str = "video/mp4") -> str:
    """
    Uploads bytes to GCS.
    """
    client = get_upload_client()
    bucket = client.bucket(GCS_BUCKET_NAME)
    blob = bucket.blob(destination_blob_name)

    blob.upload_from_string(data, content_type=content_type)
    
    return f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{destination_blob_name}"

def download_blob_to_bytes(gcs_url_or_uri: str) -> bytes:
    """
    Downloads a GCS blob to bytes using the ADC client.
    Handles gs://, path-style, and virtual-hosted URLs.
    """
    if not gcs_url_or_uri:
        return b""
    
    gs_uri = https_to_gs(gcs_url_or_uri)
    if not gs_uri.startswith("gs://"):
        # Not a GCS URL, try to download via requests
        resp = requests.get(gcs_url_or_uri, timeout=10)
        resp.raise_for_status()
        return resp.content
        
    parts = gs_uri.replace("gs://", "").split("/")
    bucket_name = parts[0]
    blob_name = "/".join(parts[1:])
    
    client = get_upload_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    
    return blob.download_as_bytes()
