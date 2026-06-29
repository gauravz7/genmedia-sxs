import os
import time
import fal_client
from dotenv import load_dotenv
from util.gcs_utils import upload_from_url, get_signed_url, download_blob_to_bytes
from typing import Optional, List

# Load environment variables
load_dotenv()

# Ensure FAL_KEY is available
fal_key = os.getenv("FAL_KEY")
if not fal_key:
    print("WARNING: FAL_KEY not found in environment variables.")

def _ensure_accessible_to_fal(url: str) -> str:
    """
    Ensures a URL is accessible to FAL.
    If it's a GCS URL, we download it via backend (using working ADC) 
    and upload it to FAL's temporary storage to bypass signature issues.
    """
    if not url:
        return url
    
    is_gcs = (
        url.startswith("gs://") or 
        "storage.googleapis.com" in url
    )
    
    if is_gcs:
        try:
            data = download_blob_to_bytes(url)
            # Use fal_client.upload for bytes directly
            ext = url.split("?")[0].split(".")[-1].lower()
            content_type = "image/jpeg" if ext in ["jpg", "jpeg"] else "image/png"
            import re as _re
            raw_name = url.split("?")[0].split("/")[-1] or "asset.png"
            safe_name = _re.sub(r"[^A-Za-z0-9._-]", "_", raw_name)  # fal needs ASCII names
            if not safe_name.strip("._-"):
                safe_name = f"asset.{ext}" if ext.isascii() else "asset.png"
            fal_url = fal_client.upload(data, content_type=content_type, file_name=safe_name)
            return fal_url
        except Exception as e:
            print(f"Error proxying GCS URL to FAL: {e}")
            # Fallback to signed URL if proxy fails, though if signing is broken this will still fail
            return get_signed_url(url)
    return url

async def generate_with_fal(model_id: str, prompt: str, ratio: str = "16:9", image_url: Optional[str] = None, end_image_url: Optional[str] = None, reference_images: Optional[List[str]] = None, mode: str = "t2v", reference_videos: Optional[List[str]] = None):
    """
    Generates a video using any FAL model ID.
    Supports T2V, I2V, F2F, and R2V (Subject References).
    Automatically signs GCS URLs for access.
    """
    start_time = time.time()
    try:
        arguments = {
            "prompt": prompt,
        }
        
        # Ensure inputs are accessible to FAL (Proxy if GCS)
        image_url = _ensure_accessible_to_fal(image_url)
        end_image_url = _ensure_accessible_to_fal(end_image_url)
        if reference_images:
            reference_images = [_ensure_accessible_to_fal(url) for url in reference_images]
        if reference_videos:
            reference_videos = [_ensure_accessible_to_fal(url) for url in reference_videos if url]
        
        # Handle aspect ratio and duration based on model family & version
        is_kling_new_gen = "kling-video/v3" in model_id or "kling-video/o3" in model_id
        is_kling_v3 = "kling-video/v3" in model_id
        is_grok = "grok-imagine" in model_id
        is_seedance_2_r2v = model_id == "bytedance/seedance-2.0/reference-to-video"

        if "kling" in model_id:
            if is_kling_new_gen:
                arguments["aspect_ratio"] = ratio
                arguments["generate_audio"] = True
            else:
                arguments["ratio"] = ratio
            arguments["duration"] = 10 # Kling maxes at 10 (int)
        elif is_grok:
            arguments["aspect_ratio"] = ratio
            arguments["duration"] = 10 # Grok default
        elif is_seedance_2_r2v:
            arguments["aspect_ratio"] = ratio
            arguments["duration"] = "10"
            arguments["generate_audio"] = True
        elif "seedance-2.0" in model_id:
            arguments["aspect_ratio"] = ratio
            arguments["duration"] = "10"
            arguments["generate_audio"] = True
        else:
            arguments["aspect_ratio"] = ratio
            arguments["duration"] = 10 # Seedance maxes at 12
        
        # User requested 720p resolution
        arguments["resolution"] = "720p"

        # Handle input image based on mode and model family
        if mode == "i2v" and image_url:
            if is_kling_v3:
                arguments["start_image_url"] = image_url
            else:
                arguments["image_url"] = image_url
            
        if mode == "i2v" and end_image_url:
            arguments["end_image_url"] = end_image_url
            
        if mode == "r2v" and reference_images:
            clean_refs = [u for u in reference_images if u]
            if is_kling_new_gen:
                # Kling v3 specifically requests 'elements' payload mapping
                # And if R2V mode acts like 'I2V', we ensure the endpoint is used correctly
                arguments["elements"] = [{"reference_image_urls": [url]} for url in clean_refs]
                # If they passed reference images + an image_url, image_url becomes start_image_url
                if image_url:
                    arguments["start_image_url"] = image_url
            elif is_seedance_2_r2v:
                # Dedicated Seedance 2.0 R2V endpoint: plain `image_urls` list,
                # up to 9 images; refer to them in the prompt as @Image1, @Image2, ...
                arguments["image_urls"] = clean_refs[:9]
                if reference_videos:
                    arguments["video_urls"] = [u for u in reference_videos if u]
            elif "seedance" in model_id:
                arguments["reference_images"] = [{"image_url": url} for url in clean_refs]
            else:
                arguments["reference_images"] = clean_refs
        
        result = await fal_client.subscribe_async(
            model_id,
            arguments=arguments
        )
        
        # Get video URL from result
        video_url = None
        if "video" in result and isinstance(result["video"], dict) and "url" in result["video"]:
            video_url = result["video"]["url"]
        elif "video_url" in result:
            video_url = result["video_url"]
        elif "url" in result:
            video_url = result["url"]
        
        # Upload to GCS for persistence if found
        gcs_url = None
        if video_url:
            try:
                # Use job-like naming or just original filename slug
                filename = f"fal_{int(time.time())}_{os.path.basename(video_url.split('?')[0])}"
                gcs_url = upload_from_url(video_url, filename)
            except Exception as e:
                print(f"GCS Upload Error: {e}")
                gcs_url = video_url # Fallback to original

        latency = round(time.time() - start_time, 2)
        return {
            "model": model_id, 
            "status": "success", 
            "url": gcs_url or video_url,
            "latency": latency,
            "result": {
                "video": {"url": gcs_url or video_url},
                "original_url": video_url,
                "gcs_path": gcs_url
            }
        }
    except Exception as e:
        latency = round(time.time() - start_time, 2)
        return {"model": model_id, "status": "error", "error": str(e), "latency": latency}

