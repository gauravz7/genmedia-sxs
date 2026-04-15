import os
import requests
import google.auth
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

DRIVE_PARENT_FOLDER_ID = os.getenv(
    "DRIVE_PARENT_FOLDER_ID", "1yfUIQX5FnkgZ_LDtJOeKClLt1yd-rmR2"
)

_DRIVE_SERVICE = None


def _get_drive_service():
    global _DRIVE_SERVICE
    if _DRIVE_SERVICE is None:
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/drive"]
        )
        credentials.refresh(Request())
        _DRIVE_SERVICE = build("drive", "v3", credentials=credentials)
    return _DRIVE_SERVICE


def _find_or_create_folder(name: str, parent_id: str) -> str:
    """Find a subfolder by name under parent_id, or create it."""
    service = _get_drive_service()
    query = (
        f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' "
        f"and '{parent_id}' in parents and trashed = false"
    )
    results = service.files().list(
        q=query, fields="files(id, name)", spaces="drive"
    ).execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]

    # Create the folder
    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = service.files().create(body=metadata, fields="id").execute()
    return folder["id"]


def upload_video_to_drive(
    video_url: str,
    filename: str,
    batch_name: str,
) -> str:
    """
    Downloads a video from *video_url* and uploads it to Google Drive
    inside a subfolder named *batch_name* under the configured parent folder.

    Returns the Drive file ID on success, or an empty string on failure.
    """
    try:
        # Download the video bytes
        from util.gcs_utils import download_blob_to_bytes, https_to_gs

        is_gcs = (
            video_url.startswith("gs://")
            or "storage.googleapis.com" in video_url
        )
        if is_gcs:
            data = download_blob_to_bytes(video_url)
        else:
            resp = requests.get(video_url, timeout=60)
            resp.raise_for_status()
            data = resp.content

        if not data:
            print(f"Drive upload: empty data for {video_url}")
            return ""

        # Find or create the batch subfolder
        folder_id = _find_or_create_folder(batch_name, DRIVE_PARENT_FOLDER_ID)

        # Upload
        service = _get_drive_service()
        file_metadata = {
            "name": filename,
            "parents": [folder_id],
        }
        media = MediaInMemoryUpload(data, mimetype="video/mp4", resumable=True)
        uploaded = (
            service.files()
            .create(body=file_metadata, media_body=media, fields="id")
            .execute()
        )
        file_id = uploaded.get("id", "")
        print(f"Drive upload OK: {filename} -> folder {batch_name} (id={file_id})")
        return file_id
    except Exception as e:
        print(f"Drive upload error for {filename}: {e}")
        return ""
