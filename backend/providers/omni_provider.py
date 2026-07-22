import os
import asyncio
import base64
import time
from typing import List, Optional

import google.auth
from dotenv import load_dotenv
from google import genai
from google.genai import types

from util.gcs_utils import download_blob_to_bytes, https_to_gs, upload_from_bytes

load_dotenv()

PROJECT_ID = os.getenv("GCP_PROJECT_ID", "vital-octagon-19612")
OMNI_LOCATION = os.getenv("OMNI_LOCATION", "global")
OMNI_MODEL_DEFAULT = os.getenv("OMNI_MODEL_ID", "gemini-omni-flash-preview")
# Preview API revision required for the gemini-omni-flash-preview interactions API.
OMNI_API_REVISION = os.getenv("OMNI_API_REVISION", "2026-05-20")

# Projects allowlisted for Omni EAP. Anything outside this set is rejected
# rather than silently falling back to the default.
OMNI_ALLOWED_PROJECTS = {"vital-octagon-19612", "cloud-llm-preview1"}
OMNI_DEFAULT_PROJECT = os.getenv("OMNI_PROJECT", PROJECT_ID)

_cached_creds = None


def _get_creds():
    global _cached_creds
    if _cached_creds is None:
        _cached_creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
    return _cached_creds


def _image_part_from_url(url: str) -> Optional[dict]:
    """Build an Agent Platform image input part from any URL.

    Uses inline base64 so the EAP service doesn't need GCS read access.
    """
    if not url:
        return None
    ext = url.split("?")[0].split(".")[-1].lower()
    mime_type = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"

    if url.startswith("gs://") or "storage.googleapis.com" in url:
        data = download_blob_to_bytes(url)
    else:
        import requests
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.content

    return {
        "type": "image",
        "mime_type": mime_type,
        "data": base64.b64encode(data).decode("utf-8"),
    }


def _g(obj, key):
    """Read a field from either a dict or a typed object.

    Under Api-Revision 2026-05-20 the interactions API returns `steps` as plain
    dicts, so attribute access alone silently misses the video payload."""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _extract_video_bytes(interaction) -> Optional[bytes]:
    """Pull the first video payload out of an Interactions API response."""
    steps = _g(interaction, "steps") or []
    for step in steps:
        if _g(step, "type") not in (None, "model_output"):
            continue
        for part in (_g(step, "content") or []):
            data = _g(part, "data")
            if not data:
                continue
            mime = _g(part, "mime_type") or ""
            if "video" in mime or _g(part, "type") == "video":
                try:
                    return base64.b64decode(data)
                except Exception:
                    continue
    return None


async def generate_with_omni(
    prompt: str,
    ratio: str = "16:9",
    image_url: Optional[str] = None,
    model_id: str = OMNI_MODEL_DEFAULT,
    reference_images: Optional[List[str]] = None,
    mode: str = "t2v",
    project_override: Optional[str] = None,
):
    """Generate a video with Gemini Omni Flash (EAP) via the Agent Platform
    Interactions API.

    Returns the same dict shape as the Veo / FAL providers.
    """
    start_time = time.time()

    project = project_override or OMNI_DEFAULT_PROJECT
    if project not in OMNI_ALLOWED_PROJECTS:
        return {
            "model": f"Omni ({model_id})",
            "status": "error",
            "error": f"Project '{project}' not in Omni EAP allowlist {sorted(OMNI_ALLOWED_PROJECTS)}",
            "latency": 0,
        }
    label = f"Omni ({model_id} @ {project})"

    # Aspect-ratio and duration are conveyed in the prompt per EAP guidance.
    full_prompt = prompt
    hints = []
    if ratio and ratio not in prompt:
        hints.append(f"{ratio} aspect ratio")
    if not any(s in prompt.lower() for s in ("second video", "seconds.")):
        hints.append("8 second video")
    if hints:
        full_prompt = f"{prompt}. {'. '.join(hints)}."

    try:
        client = genai.Client(
            vertexai=True,
            project=project,
            location=OMNI_LOCATION,
            credentials=_get_creds(),
            http_options=types.HttpOptions(
                timeout=600000,  # ms (=10 min)
                headers={"Api-Revision": OMNI_API_REVISION},
            ),
        )

        if mode == "t2v":
            input_payload = full_prompt
        else:
            urls: list = []
            if mode == "i2v":
                if image_url:
                    urls.append(image_url)
            elif mode == "r2v":
                # Accept refs from either parameter for robustness; dedupe order-preserving.
                seen = set()
                for u in (reference_images or []) + ([image_url] if image_url else []):
                    if u and u not in seen:
                        seen.add(u)
                        urls.append(u)

            prompt_with_refs = full_prompt
            if mode == "r2v" and len(urls) > 1:
                prompt_with_refs = (
                    f"{full_prompt} Use the {len(urls)} reference images "
                    "to maintain subject and style consistency."
                )

            parts: list = [{"type": "text", "text": prompt_with_refs}]
            for u in urls:
                part = await asyncio.to_thread(_image_part_from_url, u)
                if part:
                    parts.append(part)
            input_payload = parts

        interaction = await asyncio.to_thread(
            lambda: client.interactions.create(
                model=model_id,
                input=input_payload,
            )
        )

        video_bytes = _extract_video_bytes(interaction)
        if not video_bytes:
            return {
                "model": label,
                "status": "error",
                "error": "No video returned by Omni",
                "latency": round(time.time() - start_time, 2),
            }

        filename = f"omni_{int(time.time())}.mp4"
        video_url = upload_from_bytes(video_bytes, filename)
        latency = round(time.time() - start_time, 2)

        return {
            "model": label,
            "status": "success",
            "url": video_url,
            "latency": latency,
            "result": {
                "url": video_url,
                "interaction_id": getattr(interaction, "id", None),
            },
        }
    except Exception as e:
        return {
            "model": label,
            "status": "error",
            "error": str(e),
            "latency": round(time.time() - start_time, 2),
        }
