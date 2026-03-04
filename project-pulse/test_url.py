import time
import requests

url = "https://project-pulse.storage.googleapis.com/14556955212082432148/sample_0.mp4"
start = time.time()
try:
    resp = requests.head(url, timeout=3)
    print(f"Status: {resp.status_code}")
except Exception as e:
    print(f"Error: {e}")
print(f"Time taken: {time.time() - start:.2f}s")
