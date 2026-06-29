"""GPT-image ("GPT2") provider — Text-to-Image (T2I) and edit (I2I) via FAL.

FAL endpoint slugs (verified against fal.ai docs / OpenAPI schema, 2026-06):

  * T2I  : fal-ai/gpt-image-1/text-to-image
           inputs: prompt (req), image_size, background, quality, num_images,
                   output_format, sync_mode
  * I2I  : fal-ai/gpt-image-1/edit-image
           inputs: prompt (req), image_urls (req), image_size, background,
                   quality, input_fidelity, num_images, output_format, sync_mode

`quality` enum: auto | low | medium | high  (we pass the tier from the matchup).
Output: {"images": [{"url": ..., "content_type": ..., ...}]}.

For I2I we proxy any GCS input image to FAL temporary storage via
`fal_provider._ensure_accessible_to_fal` (same trick the video FAL provider uses
to dodge GCS signature issues).

Result images are downloaded and re-uploaded to GCS `images/` for persistence,
returning the shared standard result shape:

    {"model", "url", "latency_ms", "status", "error", "quality"}

No module-level network calls beyond reading FAL_KEY from env.
"""

import os
import time
from typing import Optional

import fal_client
from dotenv import load_dotenv

from providers.fal_provider import _ensure_accessible_to_fal
from util.gcs_utils import upload_from_url

load_dotenv()

if not os.getenv("FAL_KEY"):
    print("WARNING: FAL_KEY not found in environment (gpt_image_provider).")

# --- FAL endpoint slugs + quality tiers (isolated config block) -------------
GPT_IMAGE_T2I_SLUG = "fal-ai/gpt-image-1/text-to-image"
GPT_IMAGE_I2I_SLUG = "fal-ai/gpt-image-1/edit-image"

VALID_QUALITY = {"auto", "low", "medium", "high"}

# Public-facing model identity (kept stable for the leaderboard / side_map).
GPT_IMAGE_MODEL = "gpt-image-1"


def _standard_result(model: str, **kwargs) -> dict:
    base = {"model": model}
    base.update(kwargs)
    return base


def _slug(value) -> str:
    import re
    s = str(value) if value is not None else "img"
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s or "img"


def _norm_quality(quality: Optional[str]) -> str:
    q = (quality or "medium").strip().lower()
    return q if q in VALID_QUALITY else "medium"


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
    # Fallbacks for alternate shapes.
    if isinstance(result.get("image"), dict):
        return result["image"].get("url")
    return result.get("url")


async def generate_gpt_image(
    prompt: str,
    quality: str = "medium",
    input_image_url: Optional[str] = None,
    case_id: str = "case",
    image_size: str = "auto",
) -> dict:
    """Generate (T2I) or edit (I2I) one image on GPT-image via FAL at the given
    quality tier. I2I is selected when `input_image_url` is provided.

    Returns the standard result dict; errors are captured (never raised).
    """
    start = time.time()
    q = _norm_quality(quality)
    label = f"{GPT_IMAGE_MODEL} ({q})"
    try:
        arguments = {
            "prompt": prompt or "",
            "quality": q,
            "image_size": image_size,
            "num_images": 1,
            "output_format": "png",
        }

        if input_image_url:
            accessible = _ensure_accessible_to_fal(input_image_url)
            arguments["image_urls"] = [accessible]
            slug = GPT_IMAGE_I2I_SLUG
        else:
            slug = GPT_IMAGE_T2I_SLUG

        result = await fal_client.subscribe_async(slug, arguments=arguments)

        image_url = _extract_image_url(result)
        if not image_url:
            return _standard_result(
                label, status="error", error="GPT-image returned no image URL",
                latency_ms=round((time.time() - start) * 1000), quality=q,
            )

        # Persist to GCS for stable serving.
        gcs_url = image_url
        try:
            filename = f"images/gptimg_{_slug(case_id)}_{q}_{int(time.time()*1000)}.png"
            gcs_url = upload_from_url(image_url, filename)
        except Exception as e:  # pragma: no cover - fall back to FAL url
            print(f"[gpt_image_provider] GCS upload failed, using FAL url: {e}")

        return _standard_result(
            label,
            status="success",
            url=gcs_url,
            latency_ms=round((time.time() - start) * 1000),
            quality=q,
            result={"url": gcs_url, "original_url": image_url},
        )
    except Exception as e:
        return _standard_result(
            label, status="error", error=str(e),
            latency_ms=round((time.time() - start) * 1000), quality=q,
        )
