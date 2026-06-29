#!/usr/bin/env python3
"""
Fast parallel bulk upload of ALL videos from GCS bucket to Google Drive.

Strategy for speed:
  1. Query Firestore to map every GCS video URL -> (batch_name, model_key)
  2. Pre-create all Drive folders (serial, to avoid races)
  3. Download each video from GCS + upload to Drive in parallel threads.
     Each thread gets its own Drive service to avoid shared-state crashes.

Usage:
    python bulk_drive_upload.py                # full run
    python bulk_drive_upload.py --dry-run      # just print what would be uploaded
    python bulk_drive_upload.py --workers 20   # increase parallelism (default 20)
"""

import argparse
import os
import subprocess
import sys
import tempfile
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv

load_dotenv()

import google.auth
from google.auth.transport.requests import Request
from google.cloud import firestore, storage
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io

# -- Config -----------------------------------------------------------------
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "vital-octagon-19612")
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "project-pulse")
DRIVE_PARENT_FOLDER_ID = os.getenv("DRIVE_PARENT_FOLDER_ID", "0ABrvNdvu6qXtUk9PVA")
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]

# -- Thread-local Drive services -------------------------------------------
_thread_local = threading.local()
_folder_cache: dict[str, str] = {}
_folder_lock = threading.Lock()
_gcs_client = None


def _get_gcs_client():
    global _gcs_client
    if _gcs_client is None:
        _gcs_client = storage.Client(project=GCP_PROJECT_ID)
    return _gcs_client


def _get_drive_service():
    """Return a per-thread Drive service (avoids shared httplib2 state)."""
    svc = getattr(_thread_local, "drive_service", None)
    if svc is None:
        creds, _ = google.auth.default(scopes=DRIVE_SCOPES)
        if not creds.valid:
            creds.refresh(Request())
        svc = build("drive", "v3", credentials=creds)
        _thread_local.drive_service = svc
    return svc


def find_or_create_folder(batch_name: str) -> str:
    """Find/create a subfolder under the parent Drive folder. Thread-safe cached."""
    with _folder_lock:
        if batch_name in _folder_cache:
            return _folder_cache[batch_name]

    svc = _get_drive_service()
    q = (
        f"name = '{batch_name}' and mimeType = 'application/vnd.google-apps.folder' "
        f"and '{DRIVE_PARENT_FOLDER_ID}' in parents and trashed = false"
    )
    results = svc.files().list(
        q=q, fields="files(id, name)", spaces="drive",
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    files = results.get("files", [])

    if files:
        fid = files[0]["id"]
    else:
        meta = {
            "name": batch_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [DRIVE_PARENT_FOLDER_ID],
        }
        folder = svc.files().create(
            body=meta, fields="id", supportsAllDrives=True,
        ).execute()
        fid = folder["id"]

    with _folder_lock:
        _folder_cache[batch_name] = fid
    return fid


def delete_existing_in_folder(folder_id: str, filename: str):
    """Delete all copies of a file in a Drive folder (for --force replace)."""
    svc = _get_drive_service()
    q = (
        f"name = '{filename}' "
        f"and '{folder_id}' in parents and trashed = false"
    )
    results = svc.files().list(
        q=q, fields="files(id)", spaces="drive",
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    for f in results.get("files", []):
        svc.files().delete(fileId=f["id"], supportsAllDrives=True).execute()


def file_exists_in_folder(folder_id: str, filename: str) -> bool:
    """Check if a file already exists in a Drive folder."""
    svc = _get_drive_service()
    q = (
        f"name = '{filename}' "
        f"and '{folder_id}' in parents and trashed = false"
    )
    results = svc.files().list(
        q=q, fields="files(id)", spaces="drive",
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    return len(results.get("files", [])) > 0


# Set by main() based on --force flag
_force_replace = False


def _faststart_remux(data: bytes) -> bytes:
    """
    Remux MP4 with moov atom moved to front (faststart).
    This lets Google Drive process the video for playback immediately.
    No re-encoding -- just moves metadata, so it's instant.
    """
    tmp_in = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp_out = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    try:
        tmp_in.write(data)
        tmp_in.close()
        tmp_out.close()

        result = subprocess.run(
            ["ffmpeg", "-y", "-i", tmp_in.name,
             "-c", "copy", "-movflags", "+faststart", tmp_out.name],
            capture_output=True, timeout=30,
        )
        if result.returncode == 0:
            with open(tmp_out.name, "rb") as f:
                return f.read()
        # If ffmpeg fails, return original data
        return data
    finally:
        try:
            os.unlink(tmp_in.name)
        except OSError:
            pass
        try:
            os.unlink(tmp_out.name)
        except OSError:
            pass


def transfer_one(entry: dict) -> dict:
    """
    Download a video from GCS, remux with faststart for instant Drive
    playback, and upload to Drive. Each thread handles one video end-to-end.
    """
    blob_name = entry["blob_name"]
    filename = entry["filename"]
    batch_name = entry["batch_name"]
    t0 = time.time()

    try:
        folder_id = find_or_create_folder(batch_name)

        if _force_replace:
            # Delete existing copies before re-uploading
            delete_existing_in_folder(folder_id, filename)
        elif file_exists_in_folder(folder_id, filename):
            return {"file": filename, "batch": batch_name, "status": "skipped", "time": 0}

        # Download from GCS
        client = _get_gcs_client()
        bucket = client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(blob_name)
        data = blob.download_as_bytes()

        # Remux with faststart so Drive can process immediately
        data = _faststart_remux(data)

        # Upload to Drive using in-memory bytes
        media = MediaIoBaseUpload(
            io.BytesIO(data),
            mimetype="video/mp4",
            resumable=True,
            chunksize=10 * 1024 * 1024,  # 10 MB chunks
        )
        file_meta = {"name": filename, "parents": [folder_id]}
        svc = _get_drive_service()
        request = svc.files().create(
            body=file_meta, media_body=media, fields="id",
            supportsAllDrives=True,
        )
        response = None
        while response is None:
            _, response = request.next_chunk()

        elapsed = round(time.time() - t0, 1)
        size_mb = round(len(data) / 1024 / 1024, 1)
        return {"file": filename, "batch": batch_name, "status": "ok",
                "drive_id": response.get("id"), "time": elapsed, "size_mb": size_mb}
    except Exception as e:
        elapsed = round(time.time() - t0, 1)
        return {"file": filename, "batch": batch_name, "status": "error",
                "error": str(e), "time": elapsed}


# -- Manifest ---------------------------------------------------------------

def build_upload_manifest() -> list[dict]:
    """
    Query Firestore for all jobs. For each successful model result that has a
    GCS URL, produce a manifest entry: {gcs_url, batch_name, filename}.
    Deduplicates by (batch_name, filename), keeping the latest GCS blob.
    """
    db = firestore.Client(project=GCP_PROJECT_ID)
    docs = db.collection("eval_jobs").stream()

    best: dict[tuple[str, str], dict] = {}

    for doc in docs:
        data = doc.to_dict()
        batch_name = data.get("prompt_id") or data.get("id") or doc.id
        results = data.get("results", {})
        for model_key, res in results.items():
            if res.get("status") != "success":
                continue
            url = res.get("url") or (res.get("result", {}) or {}).get("url")
            if not url:
                continue
            blob_name = _url_to_blob(url)
            if not blob_name:
                continue
            filename = f"{model_key}.mp4"
            key = (batch_name, filename)
            if key in best:
                if blob_name > best[key]["blob_name"]:
                    best[key] = {
                        "gcs_url": f"gs://{GCS_BUCKET_NAME}/{blob_name}",
                        "blob_name": blob_name,
                        "batch_name": batch_name,
                        "filename": filename,
                    }
            else:
                best[key] = {
                    "gcs_url": f"gs://{GCS_BUCKET_NAME}/{blob_name}",
                    "blob_name": blob_name,
                    "batch_name": batch_name,
                    "filename": filename,
                }

    return list(best.values())


def _url_to_blob(url: str) -> str | None:
    """Extract the GCS blob name from various URL formats."""
    if not url:
        return None
    if url.startswith("gs://"):
        parts = url.replace("gs://", "").split("/", 1)
        return parts[1] if len(parts) > 1 else None
    if "storage.googleapis.com" in url:
        clean = url.split("?")[0]
        if ".storage.googleapis.com/" in clean:
            return clean.split(".storage.googleapis.com/", 1)[1]
        if "storage.googleapis.com/" in clean:
            after = clean.split("storage.googleapis.com/", 1)[1]
            parts = after.split("/", 1)
            return parts[1] if len(parts) > 1 else None
    if "/api/media?url=" in url:
        from urllib.parse import unquote
        inner = unquote(url.split("/api/media?url=", 1)[1])
        return _url_to_blob(inner)
    return None


# -- Main -------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Bulk upload GCS videos to Google Drive")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without uploading")
    parser.add_argument("--force", action="store_true", help="Delete existing files and re-upload")
    parser.add_argument("--workers", type=int, default=20, help="Parallel workers (default 20)")
    args = parser.parse_args()

    print("=" * 60)
    print("  BULK GCS -> Google Drive Upload")
    print("=" * 60)
    print(f"  Bucket:  gs://{GCS_BUCKET_NAME}")
    print(f"  Drive:   {DRIVE_PARENT_FOLDER_ID}")
    print(f"  Workers: {args.workers}")
    print(f"  Force:   {args.force}")
    print()

    # Step 1: Build manifest from Firestore
    print("1. Querying Firestore for job data...")
    manifest = build_upload_manifest()
    print(f"   Found {len(manifest)} videos across jobs")

    if not manifest:
        print("   Nothing to upload.")
        return

    by_batch = defaultdict(list)
    for entry in manifest:
        by_batch[entry["batch_name"]].append(entry["filename"])

    print(f"   {len(by_batch)} batch folders to create/use")
    for batch, files in sorted(by_batch.items()):
        print(f"     {batch}: {', '.join(files)}")

    if args.dry_run:
        print("\n[DRY RUN] Would upload the above. Exiting.")
        return

    # Set global force flag for worker threads
    global _force_replace
    _force_replace = args.force

    # Step 2: Pre-create all Drive folders (serial, avoids race conditions)
    print("\n2. Pre-creating Drive folders...")
    for batch_name in by_batch:
        fid = find_or_create_folder(batch_name)
        print(f"   {batch_name} -> {fid}")

    # Step 3: Parallel download-from-GCS + upload-to-Drive
    print(f"\n3. Transferring {len(manifest)} videos with {args.workers} workers...")
    t0 = time.time()

    ok = 0
    skipped = 0
    errors = 0

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(transfer_one, e): e for e in manifest}
        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            status = result["status"]
            if status == "ok":
                ok += 1
                print(f"   [{i}/{len(futures)}] OK  {result['batch']}/{result['file']}  "
                      f"{result.get('size_mb','')}MB  {result['time']}s")
            elif status == "skipped":
                skipped += 1
                print(f"   [{i}/{len(futures)}] SKIP {result['batch']}/{result['file']} (exists)")
            else:
                errors += 1
                print(f"   [{i}/{len(futures)}] ERR  {result['batch']}/{result['file']}: "
                      f"{result.get('error','?')}")

    elapsed = round(time.time() - t0, 1)

    print("\n" + "=" * 60)
    print(f"  DONE in {elapsed}s")
    print(f"  Uploaded: {ok}  |  Skipped: {skipped}  |  Errors: {errors}")
    print("=" * 60)


if __name__ == "__main__":
    main()
