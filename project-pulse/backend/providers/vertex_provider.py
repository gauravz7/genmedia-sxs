import os
import asyncio
import time
import requests
import google.auth
import google.auth.transport.requests
from google import genai
from google.genai import types
from dotenv import load_dotenv
from util.gcs_utils import upload_from_url, upload_from_bytes, https_to_gs, get_signed_url

load_dotenv()

PROJECT_ID = os.getenv("GCP_PROJECT_ID", "vital-octagon-19612")
OUTPUT_GCS = os.getenv("OUTPUT_GCS_BUCKET", "")

def _get_endpoints(model_id: str):
    """Constructs Vertex AI endpoints dynamically."""
    predict = f'https://us-central1-autopush-aiplatform.sandbox.googleapis.com/v1beta1/projects/{PROJECT_ID}/locations/us-central1/publishers/google/models/{model_id}:predictLongRunning'
    fetch = f'https://us-central1-autopush-aiplatform.sandbox.googleapis.com/v1beta1/projects/{PROJECT_ID}/locations/us-central1/publishers/google/models/{model_id}:fetchPredictOperation'
    return predict, fetch
_cached_creds = None

def _get_access_token():
    global _cached_creds
    if _cached_creds is None:
        _cached_creds, project = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
    
    auth_req = google.auth.transport.requests.Request()
    if not _cached_creds.valid:
        _cached_creds.refresh(auth_req)
    return _cached_creds.token

def _send_request(api_endpoint, data=None):
    headers = {
        'Authorization': f'Bearer {_get_access_token()}',
        'Content-Type': 'application/json'
    }
    response = requests.post(api_endpoint, headers=headers, json=data)
    response.raise_for_status()
    return response.json()

async def _fetch_operation(lro_name, fetch_endpoint):
    request = {'operationName': lro_name}
    for i in range(120): # Increased timeout for backend (20 mins)
        # Using to_thread for sync requests.post
        resp = await asyncio.to_thread(_send_request, fetch_endpoint, request)
        if 'done' in resp and resp['done']:
            return resp
        await asyncio.sleep(10)
    return None

async def _generate_with_veo_sdk(prompt: str, ratio: str = "16:9", image_url: str = None, model_id: str = "veo-3.1-generate-preview", reference_images: list = None, mode: str = "t2v"):
    """
    Specialized generation using google-genai SDK for Veo 3.1 Preview.
    """
    start_time = time.time()
    global _cached_creds
    if _cached_creds is None:
        _get_access_token()
        
    try:
        client = genai.Client(vertexai=True, project=PROJECT_ID, location="us-central1", credentials=_cached_creds)
        
        source_kwargs = {"prompt": prompt}
        if mode == "i2v" and image_url:
            source_kwargs["image"] = types.Image(gcs_uri=https_to_gs(image_url), mime_type="image/png")
        
        # In newer SDK versions, R2V references are submitted as part of the config
        # rather than the prompt/source. 
        config_refs = []
        if mode == "r2v" and reference_images:
            for ref_url in reference_images:
                if not ref_url: continue
                # We interpret jpeg or png based on extension, defaulting to jpeg
                ext = ref_url.split("?")[0].split(".")[-1].lower()
                mime_type = "image/png" if ext == "png" else "image/jpeg"
                
                config_refs.append(
                    types.VideoGenerationReferenceImage(
                        image=types.Image(gcs_uri=https_to_gs(ref_url), mime_type=mime_type),
                        reference_type="asset",
                    )
                )
        
        source = types.GenerateVideosSource(**source_kwargs)
        
        config_kwargs = {
            "aspect_ratio": ratio,
            "number_of_videos": 1, 
            "duration_seconds": 8,
            "person_generation": "allow_adult", # User reference showed allow_adult
            "generate_audio": True,
            "resolution": "720p",
            "seed": 0,
        }
        
        # Set output_gcs_uri to directly save the video to GCS
        bucket = os.getenv("GCS_BUCKET_NAME", "project-pulse")
        output_uri = OUTPUT_GCS if OUTPUT_GCS else bucket
        # Ensure it's a full gs:// URI
        if not output_uri.startswith("gs://"):
            output_uri = f"gs://{output_uri}/"
        if not output_uri.endswith("/"):
            output_uri += "/"
        config_kwargs["output_gcs_uri"] = output_uri
        
        if config_refs:
            config_kwargs["reference_images"] = config_refs
        
        config = types.GenerateVideosConfig(**config_kwargs)
        
        operation = client.models.generate_videos(
            model=model_id,
            source=source,
            config=config
        )
        
        # Poll for completion
        while not operation.done:
            await asyncio.sleep(10)
            operation = client.operations.get(operation)
        
        response = operation.response
        
        if not response or not response.generated_videos:
            return {"model": f"Veo SDK ({model_id})", "status": "error", "error": "No videos generated", "latency": round(time.time() - start_time, 2)}
        
        video_info = response.generated_videos[0].video
        
        if hasattr(video_info, 'uri') and video_info.uri:
            video_url = video_info.uri
        else:
            video_bytes = video_info.video_bytes
            # Upload bytes to GCS
            filename = f"veo_sdk_{int(time.time())}.mp4"
            video_url = upload_from_bytes(video_bytes, filename)
        
        latency = round(time.time() - start_time, 2)
        
        return {
            "model": f"Veo SDK ({model_id})", 
            "status": "success", 
            "url": video_url,
            "latency": latency,
            "result": {
                "url": video_url,
                "operation_id": operation.name
            }
        }
    except Exception as e:
        return {"model": f"Veo SDK ({model_id})", "status": "error", "error": str(e), "latency": round(time.time() - start_time, 2)}

async def generate_with_veo(prompt: str, ratio: str = "16:9", image_url: str = None, model_id: str = "veo-2.0-generate-001", reference_images: list = None, mode: str = "t2v"):
    """
    Generates a video using Veo models on Vertex AI.
    If model_id is a preview one, it routes to the SDK implementation.
    """
    if "preview" in model_id:
        return await _generate_with_veo_sdk(prompt, ratio, image_url, model_id, reference_images, mode=mode)
    
    start_time = time.time()
    max_retries = 3
    retry_delay = 30 # seconds
    
    for attempt in range(max_retries + 1):
        try:
            predict_endpoint, fetch_endpoint = _get_endpoints(model_id)
            
            instance = {"prompt": prompt}
            
            if mode == "i2v" and image_url:
                gcs_uri = https_to_gs(image_url)
                
                # If it's still an HTTPS URL, it might be a general web URL or a GCS URL that we need to sign and upload
                if gcs_uri.startswith("http"):
                    filename = f"veo_input_{int(time.time())}_{os.path.basename(image_url.split('?')[0])}"
                    uploaded_url = upload_from_url(image_url, filename)
                    gcs_uri = https_to_gs(uploaded_url)
                
                ext = gcs_uri.split("?")[0].split(".")[-1].lower()
                mime_type = "image/jpeg" if ext in ["jpg", "jpeg"] else "image/png"
                instance["image"] = {"gcsUri": gcs_uri, "mimeType": mime_type}
            
            if mode == "r2v" and reference_images:
                vertex_refs = []
                for ref_url in reference_images:
                    if not ref_url: continue
                    gcs_uri = https_to_gs(ref_url)
                    if gcs_uri.startswith("http"):
                        filename = f"veo_ref_{int(time.time())}_{os.path.basename(ref_url.split('?')[0])}"
                        uploaded_url = upload_from_url(ref_url, filename)
                        gcs_uri = https_to_gs(uploaded_url)
                    
                    ext = gcs_uri.split("?")[0].split(".")[-1].lower()
                    mime_type = "image/jpeg" if ext in ["jpg", "jpeg"] else "image/png"
                    vertex_refs.append({"gcsUri": gcs_uri, "mimeType": mime_type})
                
                if vertex_refs:
                    # For Veo 3.1 R2V, it uses 'reference_images' in the instance
                    instance["reference_images"] = vertex_refs
            
            # Ensure storageUri is a valid gs:// URI
            storage_uri = OUTPUT_GCS if OUTPUT_GCS else os.getenv("GCS_BUCKET_NAME", "project-pulse")
            if not storage_uri.startswith("gs://"):
                storage_uri = f"gs://{storage_uri}/"
            if not storage_uri.endswith("/"):
                storage_uri += "/"

            parameters = {
                "storageUri": storage_uri,
                "sampleCount": 1,
                "seed": 777,
                "aspectRatio": ratio,
                "durationSeconds": 8,
                "enhancePrompt": "veo-3.1" in model_id, # Mandatory for Veo 3.1
                "personGeneration": "allow_adult",
            }
            
            req_data = {
                "instances": [instance],
                "parameters": parameters
            }
            
            # Start PredictLongRunning
            resp = _send_request(predict_endpoint, req_data)
            lro_name = resp.get('name')
            
            if not lro_name:
                latency = round(time.time() - start_time, 2)
                return {"model": f"Veo ({model_id})", "status": "error", "error": "No LRO name returned", "latency": latency}
                
            # Poll for completion
            result = await _fetch_operation(lro_name, fetch_endpoint)
            
            latency = round(time.time() - start_time, 2)
            if result and 'response' in result:
                videos = result['response'].get('videos', [])
                if videos:
                    final_url = videos[0].get('gcsUri')
                    # Ensure we aren't returning anything with query params if it's HTTPS
                    if final_url and final_url.startswith("https"):
                        final_url = final_url.split("?")[0]
                    
                    return {
                        "model": f"Veo ({model_id})", 
                        "status": "success", 
                        "url": final_url,
                        "latency": latency,
                        "result": {
                            "url": final_url,
                            "operation_id": lro_name
                        }
                    }
            
            # If we get here, it either timed out or had an error
            err_msg = "Generation timed out or failed"
            if result and 'error' in result:
                error_obj = result['error']
                # Vertex Error Code 8: High load/Service Unavailable
                if isinstance(error_obj, dict) and error_obj.get('code') == 8 and attempt < max_retries:
                    print(f"Vertex high load (code 8), retrying in {retry_delay}s... (Attempt {attempt+1}/{max_retries})")
                    time.sleep(retry_delay)
                    continue
                err_msg = f"Vertex Error: {error_obj}"
                
            return {"model": f"Veo ({model_id})", "status": "error", "error": err_msg, "latency": latency}
            
        except Exception as e:
            latency = round(time.time() - start_time, 2)
            err_str = str(e).lower()
            is_transient = "503" in str(e) or "high load" in err_str or "ssl" in err_str or "eof" in err_str or "connection" in err_str
            if is_transient and attempt < max_retries:
                print(f"Vertex transient error ({e}), retrying in {retry_delay}s... (Attempt {attempt+1}/{max_retries})")
                time.sleep(retry_delay)
                continue
            return {"model": f"Veo ({model_id})", "status": "error", "error": str(e), "latency": latency}


async def generate_tags_with_gemini(prompt: str, start_image_url: str = None, end_image_url: str = None, reference_images: list = None):
    """
    Uses Gemini to suggest 3 relevant tags for a scenario.
    """
    global _cached_creds
    if _cached_creds is None:
        _get_access_token()
        
    try:
        client = genai.Client(vertexai=True, project=PROJECT_ID, location="us-central1", credentials=_cached_creds)
        
        categories = [
            "🚗 Transport", "🎥 3D animation", "☀️ Outdoor", "💡 Specific lighting", 
            "🌊 Water", "🎾 Physics", "🎥 Moving camera", "📝 Text", 
            "🌿 Nature", "🔬 Technology", "🧙 Fantasy", "🔮 Abstract", 
            "🏢 Buildings", "🏠 Indoor", "👤 People", "📄 Short prompt", 
            "⚽️ Sports", "⚡️ Weather and effects", "⚔️ Action", "📋 Long prompt", 
            "🍕 Food", "🦁 Animals", "🎞️ Multi-scene", "👗 Fashion", 
            "🎭 Cartoon and anime", "📷 Photorealistic", "💻 Screens", 
            "🏰 Specific location or era", "🚀 Sci Fi"
        ]
        cat_str = ", ".join(categories)
        
        # Build image parts first
        image_parts = []
        all_images = []
        if start_image_url: all_images.append(start_image_url)
        if end_image_url: all_images.append(end_image_url)
        if reference_images: all_images.extend(reference_images)

        for img_url in all_images[:3]:
            if not img_url: continue
            ref_gcs = img_url
            if img_url.startswith("https://storage.googleapis.com/"):
                parts = img_url.replace("https://storage.googleapis.com/", "").split("/")
                ref_gcs = f"gs://{parts[0]}/{'/'.join(parts[1:])}"
            image_parts.append(
                types.Part(
                    file_data=types.FileData(file_uri=ref_gcs, mime_type="image/png")
                )
            )

        has_images = len(image_parts) > 0
        image_context = " Analyze both the images and the text prompt to determine tags." if has_images else ""

        contents = [
            f"You are a tagging system. Pick exactly 3 tags from this list:\n{cat_str}\n\n"
            f"Rules:\n"
            f"- Return ONLY 3 tags from the list above, nothing else.\n"
            f"- Output format: tag1, tag2, tag3\n"
            f"- Do NOT output any explanation, commentary, or the prompt text.\n"
            f"- If images show real people/photos, include '📷 Photorealistic' and '👤 People'.{image_context}\n\n"
            f"Prompt: {prompt}"
        ]
        contents.extend(image_parts)

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents
        )

        text = response.text.strip()
        raw_tags = [t.strip() for t in text.split(",") if t.strip()]
        # Validate: only keep tags that match the predefined categories
        valid_tags = [t for t in raw_tags if t in categories]
        # If validation filtered too many, try fuzzy match (emoji prefix)
        if len(valid_tags) < 3:
            for raw in raw_tags:
                if raw in valid_tags:
                    continue
                for cat in categories:
                    if cat not in valid_tags and (raw in cat or cat.split(" ", 1)[-1].lower() in raw.lower()):
                        valid_tags.append(cat)
                        break
                if len(valid_tags) >= 3:
                    break
        return valid_tags[:3] if valid_tags else ["📷 Photorealistic", "👤 People", "🏠 Indoor"]
    except Exception as e:
        print(f"Error generating tags: {e}")
        return ["🎥 3D animation", "🌿 Nature", "📷 Photorealistic"] # Fallback


async def translate_to_english(text: str) -> str:
    """Translate arbitrary-language text to English using Gemini 2.5 Flash.

    Returns the text unchanged if it is already English. Used by the SxS
    Translate button for quick on-screen translations of prompts.
    """
    if not text or not text.strip():
        return ""
    global _cached_creds
    if _cached_creds is None:
        _get_access_token()
    client = genai.Client(vertexai=True, project=PROJECT_ID, location="us-central1", credentials=_cached_creds)
    resp = await asyncio.to_thread(
        client.models.generate_content,
        model="gemini-2.5-flash",
        contents=[
            "Translate the following text to English. If it is already English, "
            "return it unchanged. Output ONLY the translation — no preamble, notes, "
            "or quotation marks.\n\n" + text
        ],
    )
    return (resp.text or "").strip()
