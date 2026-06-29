import time
import asyncio

st = time.time()
from util.gcs_utils import get_signed_url
from main import jobs_manager

print(f"imports: {time.time()-st:.2f}s")
st = time.time()

# this triggers the Firestore stream over all jobs
for _ in range(5):
    all_jobs = list(jobs_manager.jobs.values())

print(f"jobs_manager.jobs list creation from firestore stream: {time.time()-st:.2f}s")

