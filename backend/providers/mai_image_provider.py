"""MAI image provider — Microsoft MAI-Image-2.5 via FAL (T2I + I2I/edit).

FAL slugs:
  * T2I  : microsoft/mai-image-2.5
           inputs: prompt (req), aspect_ratio, num_images, output_format
  * I2I  : microsoft/mai-image-2.5/edit
           inputs: prompt (req), image_urls (req), aspect_ratio, num_images,
                   output_format

aspect_ratio enum: auto, 1:1, 4:3, 3:4, 16:9, 9:16, 3:2, 2:3 (no quality/resolution
tiers). Output: {"images": [{"url": ...}], "description": ...}.

Mirrors the shared standard result shape used by the other image providers.
"""

import os
import time
from typing import Optional

import fal_client
from dotenv import load_dotenv

from providers.fal_provider import _ensure_accessible_to_fal
from util.gcs_utils import upload_from_url
from util.ratelimit import limited

load_dotenv()

if not os.getenv("FAL_KEY"):
    print("WARNING: FAL_KEY not found in environment (mai_image_provider).")

MAI_T2I_SLUG = os.getenv("MAI_T2I_SLUG", "microsoft/mai-image-2.5")
MAI_I2I_SLUG = os.getenv("MAI_I2I_SLUG", "microsoft/mai-image-2.5/edit")
MAI_IMAGE_MODEL = os.getenv("MAI_IMAGE_MODEL", "mai-image-2.5")

_VALID_AR = {"auto", "1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3"}


def _standard_result(model: str, **kwargs) -> dict:
    base = {"model": model}
    base.update(kwargs)
    return base


def _slug(value) -> str:
    import re
    s = str(value) if value is not None else "img"
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s or "img"


def _aspect(aspect_ratio: Optional[str]) -> str:
    ar = (aspect_ratio or "").strip().lower()
    return ar if ar in _VALID_AR else "auto"


def _extract_image_url(result) -> Optional[str]:
    if not isinstance(result, dict):
        return None
    images = result.get("images")
    if isinstance(images, list) and images:
        first = images[0]
        if isinstance(first, dict):
            return first.get("url")
        if isinstance(first, str):
            return first
    if isinstance(result.get("image"), dict):
        return result["image"].get("url")
    return result.get("url")


async def generate_mai_image(
    prompt: str,
    input_image_url: Optional[str] = None,
    case_id: str = "case",
    aspect_ratio: Optional[str] = None,
    resolution: Optional[str] = None,  # accepted for interface parity; MAI has no tier
) -> dict:
    """Generate (T2I) or edit (I2I) one image on MAI-Image-2.5 via FAL.
    I2I is selected when `input_image_url` is provided. Errors captured (never raised)."""
    start = time.time()
    label = MAI_IMAGE_MODEL
    try:
        arguments = {
            "prompt": prompt or "",
            "aspect_ratio": _aspect(aspect_ratio),
            "num_images": 1,
            "output_format": "png",
        }
        if input_image_url:
            arguments["image_urls"] = [_ensure_accessible_to_fal(input_image_url)]
            slug = MAI_I2I_SLUG
        else:
            slug = MAI_T2I_SLUG

        result = await limited("fal", lambda: fal_client.subscribe_async(slug, arguments=arguments))
        image_url = _extract_image_url(result)
        if not image_url:
            return _standard_result(
                label, status="error", error="MAI returned no image URL",
                latency_ms=round((time.time() - start) * 1000),
            )

        gcs_url = image_url
        try:
            filename = f"images/maiimg_{_slug(case_id)}_{int(time.time()*1000)}.png"
            gcs_url = upload_from_url(image_url, filename)
        except Exception as e:  # pragma: no cover
            print(f"[mai_image_provider] GCS upload failed, using FAL url: {e}")

        return _standard_result(
            label,
            status="success",
            url=gcs_url,
            latency_ms=round((time.time() - start) * 1000),
            result={"url": gcs_url, "original_url": image_url},
        )
    except Exception as e:
        return _standard_result(
            label, status="error", error=str(e),
            latency_ms=round((time.time() - start) * 1000),
        )
