import time
from google.cloud import storage

from util.gcs_utils import get_signed_url, get_signing_credentials

start = time.time()
cred = get_signing_credentials()
print(f"Cred load took {time.time()-start:.2f}s")

start = time.time()
client = storage.Client(project="vital-octagon-19612", credentials=cred)
bucket = client.bucket("project-pulse")
blob = bucket.blob("fal_1772180943_pGu9SRgRLU8QQd7zboPDF_output.mp4")
print(f"Client init took {time.time()-start:.2f}s")

start = time.time()
get_signed_url("https://project-pulse.storage.googleapis.com/fal_1772180943_pGu9SRgRLU8QQd7zboPDF_output.mp4")
print(f"Sign 1 took {time.time()-start:.2f}s")

start = time.time()
get_signed_url("https://project-pulse.storage.googleapis.com/14556955212082432148/sample_0.mp4")
print(f"Sign 2 took {time.time()-start:.2f}s")

start = time.time()
get_signed_url("https://project-pulse.storage.googleapis.com/test")
print(f"Sign 3 took {time.time()-start:.2f}s")

