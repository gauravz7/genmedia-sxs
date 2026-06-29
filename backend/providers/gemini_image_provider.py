"""Gemini image provider — Text-to-Image (T2I) and Image-edit (I2I) via google.genai.

Uses service-account ADC (no API key) through the Vertex AI path:

    client = genai.Client(vertexai=True, project=PROJECT_ID, location="global")

The image-output call (google-genai 1.75.0) is:

    resp = client.models.generate_content(
        model=<model>,
        contents=[<text>, <optional inline image Part>],
        config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
    )

The image bytes come back on
`resp.candidates[0].content.parts[*].inline_data.data` (raw bytes; the SDK has
already base64-decoded them). For I2I the input image is supplied as an inline
image Part alongside the text prompt (mirrors omni_provider._image_part_from_url).

Result bytes are uploaded to GCS under `images/` and the function returns the
shared standard result shape:

    {"model": ..., "url": ..., "latency_ms": ..., "status": "success"|"error",
     "error": ...}

Supported models: gemini-3.1-flash-image, gemini-3-pro-image, instant-ramen.
(instant-ramen may 404 if the project is not allowlisted — the error is returned
gracefully, never raised.)

No module-level network calls — the client is built lazily.
"""

import asyncio
import os
import time
from typing import Optional

from dotenv import load_dotenv
from google import genai
from google.genai import types

from util.gcs_utils import download_blob_to_bytes, upload_from_bytes

load_dotenv()

PROJECT_ID = os.getenv("GCP_PROJECT_ID", "vital-octagon-19612")
IMAGE_LOCATION = os.getenv("IMAGE_LOCATION", "global")

# Supported image models (kept identical to the matchup registry).
GEMINI_FLASH_IMAGE = "gemini-3.1-flash-image"
GEMINI_PRO_IMAGE = "gemini-3-pro-image"
INSTANT_RAMEN = "instant-ramen"

_client = None


def _get_client():
    """Lazily build a single Vertex genai client (ADC, no API key)."""
    global _client
    if _client is None:
        _client = genai.Client(
            vertexai=True,
            project=PROJECT_ID,
            location=IMAGE_LOCATION,
            http_options=types.HttpOptions(timeout=600000),  # ms (=10 min)
        )
    return _client


def _standard_result(model: str, **kwargs) -> dict:
    base = {"model": model}
    base.update(kwargs)
    return base


def _image_mime(url: str) -> str:
    ext = (url or "").split("?")[0].split(".")[-1].lower()
    if ext in ("jpg", "jpeg"):
        return "image/jpeg"
    if ext == "webp":
        return "image/webp"
    if ext == "gif":
        return "image/gif"
    return "image/png"


def _inline_image_part(url: str) -> types.Part:
    """Build an inline image Part from any URL (GCS proxied via ADC, else HTTP)."""
    if url and (url.startswith("gs://") or "storage.googleapis.com" in url):
        data = download_blob_to_bytes(url)
    else:
        import requests
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        data = resp.content
    return types.Part.from_bytes(data=data, mime_type=_image_mime(url))


def _extract_image(resp) -> tuple:
    """Return (bytes, mime_type) of the first inline image in a response, else
    (None, None)."""
    for cand in (getattr(resp, "candidates", None) or []):
        content = getattr(cand, "content", None)
        for part in (getattr(content, "parts", None) or []):
            inline = getattr(part, "inline_data", None)
            if inline and getattr(inline, "data", None):
                return inline.data, (getattr(inline, "mime_type", None) or "image/png")
    return None, None


def _gen_text_blob(resp) -> str:
    """Concatenate any text parts (used to surface a refusal/explanation)."""
    chunks = []
    for cand in (getattr(resp, "candidates", None) or []):
        content = getattr(cand, "content", None)
        for part in (getattr(content, "parts", None) or []):
            t = getattr(part, "text", None)
            if t:
                chunks.append(t)
    return " ".join(chunks).strip()


def _slug(value) -> str:
    import re
    s = str(value) if value is not None else "img"
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s or "img"


def _norm_resolution(resolution) -> Optional[str]:
    """Map a requested resolution to a Gemini image_size token (1K/2K/4K).
    Gemini's minimum is 1K, so 512/1024 → 1K."""
    r = str(resolution or "").strip().lower()
    if not r:
        return None
    if r in ("4k", "4096"):
        return "4K"
    if r in ("2k", "2048"):
        return "2K"
    return "1K"


async def generate_gemini_image(
    model: str,
    prompt: str,
    input_image_url: Optional[str] = None,
    case_id: str = "case",
    aspect_ratio: Optional[str] = None,
    resolution: Optional[str] = None,
) -> dict:
    """Generate (T2I) or edit (I2I) one image on a Gemini image model.

    If `input_image_url` is provided the call runs in I2I/edit mode (the input
    image is added as an inline Part alongside the prompt). Otherwise pure T2I.

    Returns the standard result dict; provider/model errors are captured as
    status="error" (never raised).
    """
    start = time.time()
    try:
        client = _get_client()

        contents = [prompt or ""]
        if input_image_url:
            part = await asyncio.to_thread(_inline_image_part, input_image_url)
            contents.append(part)

        # Build image_config from aspect_ratio + resolution. Some models may not
        # accept image_size — if a configured call errors we fall back to a basic
        # config (response_modalities only) so generation still succeeds.
        ic_kwargs = {}
        ar = (aspect_ratio or "").strip() or None
        res = _norm_resolution(resolution)
        if ar:
            ic_kwargs["aspect_ratio"] = ar
        if res:
            ic_kwargs["image_size"] = res
        config_full = types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(**ic_kwargs) if ic_kwargs else None,
        )
        config_basic = types.GenerateContentConfig(response_modalities=["IMAGE"])
        configs = [config_full] if not ic_kwargs else [config_full, config_basic]

        # The model occasionally returns no image (text-only refusal / empty
        # candidate); retry a couple of times before giving up. If a configured
        # call raises, fall through to the next (basic) config.
        last_text = ""
        img_bytes, mime = None, None
        for cfg in configs:
            for attempt in range(3):
                try:
                    resp = await asyncio.to_thread(
                        lambda cfg=cfg: client.models.generate_content(
                            model=model, contents=contents, config=cfg
                        )
                    )
                except Exception as ge:
                    last_text = f"config error: {ge}"
                    break  # try next config (e.g. drop image_size)
                img_bytes, mime = _extract_image(resp)
                if img_bytes:
                    break
                last_text = _gen_text_blob(resp)
                if attempt < 2:
                    await asyncio.sleep(3.0)
            if img_bytes:
                break

        if not img_bytes:
            msg = "Model returned no image"
            if last_text:
                msg += f" (text: {last_text[:300]})"
            return _standard_result(
                model, status="error", error=msg,
                latency_ms=round((time.time() - start) * 1000),
            )

        ext = "png"
        if mime == "image/jpeg":
            ext = "jpg"
        elif mime == "image/webp":
            ext = "webp"
        filename = f"images/img_{_slug(case_id)}_{_slug(model)}_{int(time.time()*1000)}.{ext}"
        gcs_url = upload_from_bytes(img_bytes, filename, content_type=mime)

        return _standard_result(
            model,
            status="success",
            url=gcs_url,
            latency_ms=round((time.time() - start) * 1000),
            result={"url": gcs_url, "mime_type": mime},
        )
    except Exception as e:
        return _standard_result(
            model,
            status="error",
            error=str(e),
            latency_ms=round((time.time() - start) * 1000),
        )
