"""Google Slides decks, the HTML slideware view, and its feedback store."""

import os
from typing import List, Optional

from fastapi import (APIRouter, BackgroundTasks, Depends, HTTPException,
                     Query)
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from auth import require_admin

router = APIRouter()


@router.post("/api/slides/generate", dependencies=[Depends(require_admin)])
async def generate_slides(
    batches: List[str] = Query(default=[]),
    force_new: bool = Query(default=False),
    background_tasks: BackgroundTasks = None,
):
    """Generate Google Slides presentation with Drive-embedded videos.
    - batches: list of batch names to include (empty = all)
    - force_new: create a fresh presentation instead of appending
    """
    from generate_google_slides import create_presentation
    batch_filter = batches if batches else None
    try:
        url = create_presentation(batch_filter=batch_filter, force_new=force_new)
        return {"status": "ok", "url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/slides/append/{batch_name}", dependencies=[Depends(require_admin)])
async def append_slides_for_batch(batch_name: str):
    """Append a single batch to the existing Google Slides presentation."""
    from generate_google_slides import append_batch_slides
    try:
        url = append_batch_slides(batch_name)
        if url:
            return {"status": "ok", "url": url}
        return {"status": "skipped", "message": f"{batch_name} already in presentation or no data"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/slideware")
async def serve_slideware():
    """Serve the generated HTML slideware presentation."""
    path = os.path.join(os.path.dirname(__file__), "slideware.html")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Slideware not generated yet. Run a generation first.")
    with open(path) as f:
        return HTMLResponse(content=f.read())


@router.post("/api/slideware/regenerate", dependencies=[Depends(require_admin)])
async def regenerate_slideware():
    """Regenerate the slideware HTML from current Firestore data."""
    from generate_slideware import fetch_jobs, generate_presentation
    jobs = fetch_jobs()
    result = generate_presentation(jobs, output_path=os.path.join(os.path.dirname(__file__), "slideware.html"))
    if result:
        return {"status": "ok", "message": "Generated slideware"}
    raise HTTPException(status_code=500, detail="No slides generated — no successful videos found")


@router.post("/api/slideware/pptx", dependencies=[Depends(require_admin)])
async def generate_pptx_endpoint(batches: List[str] = Query(default=[])):
    """Generate and download a PPTX with embedded videos for specified batches."""
    from generate_pptx import generate_pptx
    out_path = os.path.join(os.path.dirname(__file__), "project_pulse_export.pptx")
    batch_filter = batches if batches else None
    result = generate_pptx(batch_filter=batch_filter, output_path=out_path)
    if not result:
        raise HTTPException(status_code=500, detail="No slides generated")
    with open(out_path, "rb") as f:
        data = f.read()
    filename = "Project_Pulse.pptx"
    if batch_filter:
        filename = f"Project_Pulse_{'_'.join(batch_filter)}.pptx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/slideware/pptx/download")
async def download_existing_pptx():
    """Download the most recently generated PPTX."""
    for name in ["project_pulse_test.pptx", "project_pulse_export.pptx"]:
        path = os.path.join(os.path.dirname(__file__), name)
        if os.path.exists(path):
            with open(path, "rb") as f:
                data = f.read()
            return Response(
                content=data,
                media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                headers={"Content-Disposition": f'attachment; filename="{name}"'},
            )
    raise HTTPException(status_code=404, detail="No PPTX file found. Generate one first via POST /api/slideware/pptx")


class SlideFeedback(BaseModel):
    batch_name: str
    model_key: Optional[str] = None
    tier: str  # "pro" or "fast"
    user_name: Optional[str] = None
    comment: Optional[str] = None


@router.get("/api/slideware/feedback")
async def get_slideware_feedback():
    """Get all feedback (best picks + comments) for slideware."""
    from google.cloud import firestore as _fs
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
    docs = db.collection("slideware_feedback").stream()
    feedback = {}
    for doc in docs:
        feedback[doc.id] = doc.to_dict()
    return feedback


@router.post("/api/slideware/feedback/pick", dependencies=[Depends(require_admin)])
async def set_best_video(body: SlideFeedback):
    """Set the best video pick for a batch+tier."""
    from google.cloud import firestore as _fs
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
    doc_id = f"{body.batch_name}__{body.tier}"
    db.collection("slideware_feedback").document(doc_id).set({
        "batch_name": body.batch_name,
        "tier": body.tier,
        "best_model": body.model_key,
        "picked_by": body.user_name or "anonymous",
    }, merge=True)
    return {"status": "ok"}


@router.post("/api/slideware/feedback/comment", dependencies=[Depends(require_admin)])
async def add_comment(body: SlideFeedback):
    """Add a comment to a batch+tier."""
    from google.cloud import firestore as _fs
    import datetime
    db = _fs.Client(project=os.getenv("GCP_PROJECT_ID", "vital-octagon-19612"))
    doc_id = f"{body.batch_name}__{body.tier}"
    doc_ref = db.collection("slideware_feedback").document(doc_id)
    doc = doc_ref.get()
    existing = doc.to_dict() if doc.exists else {}
    comments = existing.get("comments", [])
    comments.append({
        "text": body.comment,
        "user": body.user_name or "anonymous",
        "timestamp": datetime.datetime.now().isoformat(),
    })
    doc_ref.set({
        "batch_name": body.batch_name,
        "tier": body.tier,
        "comments": comments,
    }, merge=True)
    return {"status": "ok", "comments": comments}
