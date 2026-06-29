import requests
import os

def test_upload():
    url = "http://localhost:8010/api/upload"
    # Create a dummy image
    with open("dummy.png", "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")
    
    with open("dummy.png", "rb") as f:
        files = {"file": ("dummy.png", f, "image/png")}
        resp = requests.post(url, files=files)
    
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.json()}")

if __name__ == "__main__":
    test_upload()
