import requests
from util.gcs_utils import get_signed_url
url = "https://storage.googleapis.com/project-pulse/fal_1772176285_IEth4E7ohMPv1zHtt7cQP_video.mp4"
signed = get_signed_url(url)
r = requests.head(signed)
print("HEAD status:", r.status_code)
if r.status_code != 200:
    r2 = requests.get(signed)
    print("GET text:", r2.text)
