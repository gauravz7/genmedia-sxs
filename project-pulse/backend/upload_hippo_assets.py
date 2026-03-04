
import os
import sys
from util.gcs_utils import upload_from_path

def main():
    assets = [
        "/Users/gauravz/.gemini/jetski/brain/9b94708f-96fc-4188-b40a-560adab43469/hippo_start_frame_1772101199265.png",
        "/Users/gauravz/.gemini/jetski/brain/9b94708f-96fc-4188-b40a-560adab43469/hippo_last_frame_1772101213015.png"
    ]
    
    for asset in assets:
        if os.path.exists(asset):
            blob_name = f"tests/{os.path.basename(asset)}"
            url = upload_from_path(asset, blob_name)
            print(f"Uploaded {asset} to {url}")
        else:
            print(f"File not found: {asset}")

if __name__ == "__main__":
    main()
