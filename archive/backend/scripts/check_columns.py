import sys
sys.path.append("/Users/gauravz/Desktop/Antigravity/SxS/project-pulse/backend")
from util.sheets_utils import get_sheets_token, get_sheet_id_from_url
import requests
import json

sheet_url = "https://docs.google.com/spreadsheets/d/1RW6lYvwv5geS1Wv0LnqzFWUco3sa47FyH42RuvK0c7g/edit?gid=0#gid=0"
sheet_id = get_sheet_id_from_url(sheet_url)

token = get_sheets_token()
url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/A1:K1"
headers = {
    "Authorization": f"Bearer {token}",
    "X-Goog-User-Project": "vital-octagon-19612"
}

resp = requests.get(url, headers=headers)
print("Columns:", resp.json())
