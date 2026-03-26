import google.auth
from google.auth.transport.requests import Request
import requests
import json
import re

def get_sheet_id_from_url(url_or_id: str) -> str:
    # If it looks like a URL, extract the ID
    match = re.search(r'/d/([a-zA-Z0-9-_]+)', url_or_id)
    if match:
        return match.group(1)
    return url_or_id.strip()

def get_sheets_token():
    # Use gcloud to get a Sheets-scoped access token (compute ADC lacks Sheets scope)
    import subprocess
    try:
        result = subprocess.run(
            ["gcloud", "auth", "print-access-token", "--scopes=https://www.googleapis.com/auth/spreadsheets"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception as e:
        print(f"gcloud token fallback failed: {e}")
    # Fallback to ADC
    credentials, _ = google.auth.default()
    if not credentials.valid:
        credentials.refresh(Request())
    return credentials.token

def read_sheet(sheet_id: str, range_name: str = "A1:L1000"):
    """Reads a sheet and returns the rows"""
    sheet_id = get_sheet_id_from_url(sheet_id)
    token = get_sheets_token()
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{range_name}"
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Goog-User-Project": "vital-octagon-19612"
    }
    
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        raise Exception(f"Failed to read sheet: {resp.text}")
    
    data = resp.json()
    return data.get("values", [])

def update_sheet_row(sheet_id: str, row_index: int, success: bool, error_msg: str = ""):
    """
    Updates the Success (J) and Error (K) columns for a specific 1-indexed row.
    J = col 10, K = col 11
    """
    sheet_id = get_sheet_id_from_url(sheet_id)
    token = get_sheets_token()
    
    # We update columns J and K (index 9 and 10 in 0-indexed terms)
    # Range is J{row_index}:K{row_index}
    range_name = f"J{row_index}:K{row_index}"
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{range_name}?valueInputOption=USER_ENTERED"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Goog-User-Project": "vital-octagon-19612"
    }
    
    payload = {
        "range": range_name,
        "majorDimension": "ROWS",
        "values": [
            [str(success), error_msg]
        ]
    }
    
    resp = requests.put(url, headers=headers, json=payload)
    if resp.status_code != 200:
        print(f"Failed to update sheet row {row_index}: {resp.text}")
    return resp.json()
