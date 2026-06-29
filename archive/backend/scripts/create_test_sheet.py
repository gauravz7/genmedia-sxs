import requests
import json
import subprocess

def create_test_sheet():
    token = subprocess.check_output(['gcloud', 'auth', 'print-access-token']).decode('utf-8').strip()
    
    # Create Sheet
    create_url = "https://sheets.googleapis.com/v4/spreadsheets"
    payload = {
        "properties": {"title": "Test Batch Jobs (T2V & I2V)"},
        "sheets": [
            {
                "properties": {
                    "gridProperties": {"columnCount": 11}
                }
            }
        ]
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    print("Creating sheet...")
    resp = requests.post(create_url, headers=headers, json=payload)
    if resp.status_code != 200:
        print("Failed to create sheet:", resp.text)
        return
        
    data = resp.json()
    sheet_id = data["spreadsheetId"]
    sheet_url = data["spreadsheetUrl"]
    print(f"Created sheet: {sheet_url}")
    
    # Populate Rows
    update_url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/A1:K3?valueInputOption=USER_ENTERED"
    
    rows = [
        ["Prompt ID", "Mode", "Text Prompt", "Start Image", "Last Image", "Ref Image 1", "Ref Image 2", "Ref Image 3", "Model", "Success", "Error"],
        ["BATCH_001", "t2v", "A glowing neon jellyfish swimming through a cyber city", "", "", "", "", "", "kling-o3-standard-t2v", "False", ""],
        ["BATCH_002", "i2v", "A red sports car drifting on a snowy mountain", "https://project-pulse.storage.googleapis.com/uploads/1772380748_image2v.png", "", "", "", "", "veo-3-1-fast-preview-i2v", "False", ""]
    ]
    
    payload_update = {
        "values": rows
    }
    
    print("Updating rows...")
    resp = requests.put(update_url, headers=headers, json=payload_update)
    if resp.status_code != 200:
        print("Failed to update sheet:", resp.text)
        return
        
    print(f"Successfully populated sheet!\nUse this URL: {sheet_url}")

if __name__ == "__main__":
    create_test_sheet()
