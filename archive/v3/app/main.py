"""Application factory — assembles the FastAPI app (Agent 5).

Router inclusion is wrapped in try/except so that a sibling agent's not-yet-
finished module cannot take down the whole service: a failed import is logged and
skipped, and the rest of the API still boots. This keeps the integration surface
resilient while modules land in parallel.
"""
from __future__ import annotations

import importlib
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger("app.main")

# (module path, router attribute) for every router we try to mount.
_ROUTER_MODULES: tuple[tuple[str, str], ...] = (
    ("app.routers.executions", "router"),
    ("app.routers.comparisons", "router"),
    ("app.routers.video", "router"),
    ("app.routers.image", "router"),
    ("app.routers.tts", "router"),
    ("app.routers.models", "router"),
    ("app.routers.analytics", "router"),
    ("app.routers.votes", "router"),
    ("app.routers.compare", "router"),
    ("app.routers.suites", "router"),
    ("app.routers.admin", "router"),
    ("app.routers.media", "router"),
)


def _include_routers(app: FastAPI) -> None:
    for module_path, attr in _ROUTER_MODULES:
        try:
            module = importlib.import_module(module_path)
            app.include_router(getattr(module, attr))
        except Exception:  # noqa: BLE001 - resilience: never let one router kill boot
            logger.exception("Skipping router %s (import/registration failed)", module_path)


def create_app() -> FastAPI:
    app = FastAPI(title="GenMedia SxS v3", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    _include_routers(app)
    return app


app = create_app()
