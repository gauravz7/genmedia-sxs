import requests
from util.gcs_utils import get_signed_url
url = "https://storage.googleapis.com/project-pulse/fal_1772176285_IEth4E7ohMPv1zHtt7cQP_video.mp4"
signed = get_signed_url(url)
r = requests.head(signed)
print(r.status_code)
