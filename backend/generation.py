"""The legacy multi-model video generation engine.

Drives `POST /api/generate` and the admin retry endpoint. The live video path is
`/api/sxs/*` (see `video_routes.py`); this remains for the older flow.
"""

import asyncio
import os
import time
from typing import List, Optional

from pydantic import BaseModel

from providers.fal_provider import generate_with_fal
from providers.omni_provider import generate_with_omni
from providers.vertex_provider import generate_with_veo
from registry import RegisteredModel
from store import jobs_manager


class PromptRequest(BaseModel):
    text: str
    categories: List[str] = []
    ratio: str = "16:9"
    prompt_id: Optional[str] = None
    start_image_url: Optional[str] = None
    end_image_url: Optional[str] = None
    reference_image_url: Optional[str] = None
    reference_images: Optional[List[str]] = None
    model_ids: Optional[List[str]] = None
    mode: Optional[str] = None
    omni_project: Optional[str] = None  # 'vital-octagon-19612' or 'cloud-llm-preview1'

    def __init__(self, **data):
        # Migrate legacy single-category field
        if "category" in data:
            cat = data.pop("category")
            if cat and not data.get("categories"):
                data["categories"] = [cat]
        super().__init__(**data)


async def _run_generation_background(job_id: str, target_models: List[RegisteredModel], request: PromptRequest, initiation_time: float):
    try:
        tasks = []
        model_keys = []

        for model in target_models:
            model_keys.append(model.id)
            if model.provider == "vertex":
                img_to_pass = request.start_image_url or request.reference_image_url
                if not img_to_pass and request.reference_images:
                    img_to_pass = request.reference_images[0]
                tasks.append(generate_with_veo(
                    request.text, request.ratio, img_to_pass, model.model_id,
                    request.reference_images, mode=model.type,
                ))
            elif model.provider == "fal":
                tasks.append(generate_with_fal(
                    model.model_id, request.text, request.ratio,
                    request.start_image_url or request.reference_image_url,
                    request.end_image_url, request.reference_images, mode=model.type,
                ))
            elif model.provider == "omni":
                img_to_pass = request.start_image_url or request.reference_image_url
                if not img_to_pass and request.reference_images:
                    img_to_pass = request.reference_images[0]
                tasks.append(generate_with_omni(
                    request.text, request.ratio, img_to_pass, model.model_id,
                    request.reference_images, mode=model.type,
                    project_override=request.omni_project,
                ))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        response_results = {}
        for i, key in enumerate(model_keys):
            res = results[i]
            if isinstance(res, Exception):
                response_results[key] = {"status": "error", "error": str(res)}
            else:
                if "latency" not in res:
                    res["latency"] = round(time.time() - initiation_time, 2)
                response_results[key] = res

        # Write results directly to Firestore to avoid stale cache issues.
        # The cache may have expired during the long generation (3-10 min),
        # causing jobs_manager.jobs.get() to return None and silently drop results.
        from google.cloud import firestore as _fs
        db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
        doc_ref = db.collection("eval_jobs").document(job_id)
        doc = doc_ref.get()
        if doc.exists:
            current = doc.to_dict()
            existing_results = current.get("results", {})
            generation_history = current.get("generation_history", {})

            for k, v in response_results.items():
                # Archive previous successful result before overwriting
                if k in existing_results and existing_results[k].get("status") == "success":
                    prev = existing_results[k]
                    if k not in generation_history:
                        generation_history[k] = []
                    generation_history[k].append({
                        **prev,
                        "archived_at": time.time(),
                    })
                    print(f"Archived previous result for {k} (version {len(generation_history[k])})")
                existing_results[k] = v

            update_data = {"results": existing_results}
            if generation_history:
                update_data["generation_history"] = generation_history
            doc_ref.update(update_data)
            jobs_manager.invalidate_cache()
            print(f"Background Job {job_id} completed. Updated {len(response_results)} model(s).")

            # Regenerate HTML slideware with latest results
            batch_name = current.get("prompt_id") or job_id
            try:
                from generate_slideware import generate_for_batch
                generate_for_batch(batch_name)
            except Exception as slideware_err:
                print(f"Slideware generation failed for {batch_name}: {slideware_err}")
        else:
            print(f"ERROR: Job {job_id} not found in Firestore after generation.")
    except Exception as e:
        print(f"Error in background generation for job {job_id}: {e}")
        # Try to mark failed models as error in Firestore
        try:
            from google.cloud import firestore as _fs
            db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
            doc_ref = db.collection("eval_jobs").document(job_id)
            doc = doc_ref.get()
            if doc.exists:
                current = doc.to_dict()
                existing_results = current.get("results", {})
                for key in model_keys:
                    if existing_results.get(key, {}).get("status") == "generating":
                        existing_results[key] = {"status": "error", "error": str(e)}
                doc_ref.update({"results": existing_results})
                jobs_manager.invalidate_cache()
        except Exception:
            pass
