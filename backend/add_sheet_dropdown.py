import sys
import json
import requests
sys.path.append("/Users/gauravz/Desktop/Antigravity/SxS/project-pulse/backend")
from util.sheets_utils import get_sheets_token, get_sheet_id_from_url

sheet_url = "https://docs.google.com/spreadsheets/d/1RW6lYvwv5geS1Wv0LnqzFWUco3sa47FyH42RuvK0c7g/edit?gid=0#gid=0"
sheet_id = get_sheet_id_from_url(sheet_url)

# Load models safely
with open("/Users/gauravz/Desktop/Antigravity/SxS/project-pulse/backend/models.json", "r") as f:
    models_dict = json.load(f)

model_ids = list(models_dict.keys())

token = get_sheets_token()
headers = {
    "Authorization": f"Bearer {token}",
    "X-Goog-User-Project": "vital-octagon-19612"
}

# Get sheetId
url_get = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}"
resp_get = requests.get(url_get, headers=headers)
if resp_get.status_code != 200:
    print("Error fetching sheet metadata:", resp_get.text)
    sys.exit(1)

sheet_info = resp_get.json()
first_sheet_id = sheet_info['sheets'][0]['properties']['sheetId']

# Rule for Model column
model_validation_rule = {
    "condition": {
        "type": "ONE_OF_LIST",
        "values": [{"userEnteredValue": m} for m in model_ids]
    },
    "showCustomUi": True,
    "strict": True
}

# Rule for Mode column
mode_validation_rule = {
    "condition": {
        "type": "ONE_OF_LIST",
        "values": [
            {"userEnteredValue": "t2v"},
            {"userEnteredValue": "i2v"},
            {"userEnteredValue": "r2v"}
        ]
    },
    "showCustomUi": True,
    "strict": True
}

request_body = {
    "requests": [
        {
            "setDataValidation": {
                "range": {
                    "sheetId": first_sheet_id,
                    "startRowIndex": 1, 
                    "startColumnIndex": 8, # Model is Col I (idx 8)
                    "endColumnIndex": 9
                },
                "rule": model_validation_rule
            }
        },
        {
            "setDataValidation": {
                "range": {
                    "sheetId": first_sheet_id,
                    "startRowIndex": 1, 
                    "startColumnIndex": 1, # Mode is Col B (idx 1)
                    "endColumnIndex": 2
                },
                "rule": mode_validation_rule
            }
        }
    ]
}

url_update = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}:batchUpdate"
resp_update = requests.post(url_update, headers=headers, json=request_body)

if resp_update.status_code == 200:
    print("Successfully added dropdowns to Mode and Model columns.")
else:
    print("Failed to add dropdowns:", resp_update.text)
