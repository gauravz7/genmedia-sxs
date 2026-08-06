"""Project Pulse / GenMedia SxS — application assembly.

This module wires the app together and owns nothing else. Every handler lives in
a router module; the sections that used to sit inline here are now:

    config.py            env constants, normalize_gcs_url
    registry.py          the cross-modality model registry
    store.py             legacy Firestore document managers
    auth.py              admin token + require_admin
    tagging.py           Gemini auto-tagging background tasks
    generation.py        the legacy multi-model generation engine
    models_routes.py     /api/models
    admin_routes.py      /api/admin/*, tags, sheets
    video_routes.py      /api/sxs/*            (the live video modality)
    image_routes.py      /api/image/*
    tts_routes.py        /api/tts/*
    intake_routes.py     /api/{sxs,image,tts}/{prompts,outputs}
    analytics_routes.py  stats, leaderboards, benchmark winmap, agreement
    media_routes.py      /api/health, /api/media
    legacy_routes.py     the pre-multi-modality endpoints
    slides_routes.py     Google Slides + slideware

Router order matters: every API router is registered BEFORE the static
catch-all mount so /api/* always wins over the Next.js export.

`registry`, `PROVIDER_TRANSPORT`, `RegisteredModel` and `require_admin` are
re-exported below because `model_resolver`, `tts_pipeline` and the test suite
reach for them as `main.<name>`.
"""

import os

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from auth import ADMIN_PASS, ADMIN_USER, _admin_token, require_admin  # noqa: F401
from config import (GCP_PROJECT_ID, GCS_BUCKET_NAME, SXS_COLLECTION,  # noqa: F401
                    SXS_RUNS_COLLECTION, SXS_VOTES_COLLECTION, VALID_RATIOS,
                    normalize_gcs_url)
from registry import PROVIDER_TRANSPORT, RegisteredModel, registry  # noqa: F401
from store import (Job, JobsManager, Prompt, PromptsManager, Vote,  # noqa: F401
                   VotesManager, jobs_manager, prompts_manager, votes_manager)

app = FastAPI(title="Project Pulse API")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    body = exc.body
    if not isinstance(body, (dict, list, str, int, float, bool, type(None))):
        body = "<non-serializable body>"
    print(f"Validation Error: {exc.errors()}")
    return JSONResponse(status_code=422, content={"detail": exc.errors(), "body": body})


app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

print(f"Starting with Project ID: {GCP_PROJECT_ID}")

# ===================================================================
# Routers — all registered before the static catch-all mount.
# ===================================================================
from admin_routes import router as admin_router          # noqa: E402
from analytics_routes import router as analytics_router  # noqa: E402
from image_routes import router as image_router          # noqa: E402
from intake_routes import router as intake_router        # noqa: E402
from legacy_routes import router as legacy_router        # noqa: E402
from media_routes import router as media_router          # noqa: E402
from models_routes import router as models_router        # noqa: E402
from slides_routes import router as slides_router        # noqa: E402
from tts_routes import router as tts_router              # noqa: E402
from video_routes import router as video_router          # noqa: E402

app.include_router(admin_router)
app.include_router(models_router)
app.include_router(video_router)
app.include_router(image_router)
app.include_router(tts_router)
app.include_router(intake_router)
app.include_router(analytics_router)
app.include_router(media_router)
app.include_router(slides_router)
app.include_router(legacy_router)


# ===================================================================
# Static files (Next.js export)
# ===================================================================
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    @app.exception_handler(404)
    async def custom_404_handler(request, exc):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        index_path = os.path.join(static_dir, "index.html")
        if os.path.exists(index_path):
            with open(index_path) as f:
                return HTMLResponse(content=f.read(), status_code=404)
        return HTMLResponse(content="Frontend not built", status_code=404)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
