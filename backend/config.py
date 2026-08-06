"""Environment configuration shared by every router.

One import point for the GCP project/bucket and the video (`sxs`) collection
names, so a module doesn't have to reach back into `main` for them.
"""

import os
from urllib.parse import unquote

from dotenv import load_dotenv

load_dotenv()

# Application Default Credentials only — a stale key file in the environment
# would silently outrank them.
os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)

GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "vital-octagon-19612")
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "project-pulse")

# Isolated test database for the SxS (Seedance vs Omni) feature — kept separate
# from the production `eval_jobs` / `votes` collections.
SXS_COLLECTION = os.getenv("SXS_COLLECTION", "sxs_jobs")
SXS_VOTES_COLLECTION = os.getenv("SXS_VOTES_COLLECTION", "sxs_votes")
SXS_RUNS_COLLECTION = os.getenv("SXS_RUNS_COLLECTION", "sxs_runs")

VALID_RATIOS = ["16:9", "9:16"]


def normalize_gcs_url(url: str) -> str:
    """Strip signed-URL query params and proxy wrappers from GCS URLs."""
    if not url:
        return url
    if "/api/media?url=" in url:
        encoded = url.split("/api/media?url=")[-1]
        return unquote(encoded)
    if "X-Goog-Signature" in url or "?X-Goog-Algorithm" in url:
        return url.split("?")[0]
    return url
