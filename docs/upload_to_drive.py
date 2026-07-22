#!/usr/bin/env python3
"""Upload the two decks (+PDFs) to a Google Drive / Shared Drive folder using ADC."""
import json, os, sys
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

FOLDER_ID = "0ABrvNdvu6qXtUk9PVA"
HERE = os.path.dirname(os.path.abspath(__file__))
FILES = [
    ("GenMedia SxS - User Guide (How to Rate).pptx",
     "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    ("GenMedia SxS - Product Overview (Leadership).pptx",
     "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    ("GenMedia SxS - User Guide (How to Rate).pdf", "application/pdf"),
    ("GenMedia SxS - Product Overview (Leadership).pdf", "application/pdf"),
    ("GenMedia SxS - VP Brief (Evaluator Program).pptx",
     "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    ("GenMedia SxS - VP Brief (Evaluator Program).pdf", "application/pdf"),
]

def creds():
    p = os.path.expanduser("~/.config/gcloud/application_default_credentials.json")
    d = json.load(open(p))
    c = Credentials(None, refresh_token=d["refresh_token"], client_id=d["client_id"],
                    client_secret=d["client_secret"],
                    token_uri="https://oauth2.googleapis.com/token",
                    scopes=["https://www.googleapis.com/auth/drive"])
    qp = d.get("quota_project_id") or "vital-octagon-19612"
    c = c.with_quota_project(qp)
    c.refresh(Request())
    return c

def main():
    svc = build("drive", "v3", credentials=creds())
    meta = svc.files().get(fileId=FOLDER_ID, supportsAllDrives=True,
                           fields="id,name,driveId").execute()
    print("Target folder:", meta.get("name"), "| driveId:", meta.get("driveId"))
    for name, mime in FILES:
        path = os.path.join(HERE, name)
        if not os.path.exists(path):
            print("  skip (missing):", name); continue
        # replace existing file with same name in the folder
        q = ("name = %r and '%s' in parents and trashed = false"
             % (name, FOLDER_ID))
        existing = svc.files().list(q=q, spaces="drive", corpora="allDrives",
                                    includeItemsFromAllDrives=True, supportsAllDrives=True,
                                    fields="files(id,name)").execute().get("files", [])
        media = MediaFileUpload(path, mimetype=mime, resumable=True)
        if existing:
            fid = existing[0]["id"]
            f = svc.files().update(fileId=fid, media_body=media,
                                   supportsAllDrives=True,
                                   fields="id,webViewLink").execute()
            print("  updated:", name, "->", f.get("webViewLink"))
        else:
            body = {"name": name, "parents": [FOLDER_ID]}
            f = svc.files().create(body=body, media_body=media,
                                   supportsAllDrives=True,
                                   fields="id,webViewLink").execute()
            print("  uploaded:", name, "->", f.get("webViewLink"))

if __name__ == "__main__":
    main()
