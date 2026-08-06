"""Admin router — a minimal stateless-token auth surface (ported from v2).

``POST /api/admin/login`` exchanges ``admin_user``/``admin_pass`` (from settings)
for a deterministic token derived from the password. Protected endpoints depend
on :func:`require_admin`, which constant-time-compares the ``X-Admin-Token``
header against that token.
"""
from __future__ import annotations

import hashlib
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from app.config import Settings
from app.deps import get_settings_dep

router = APIRouter(prefix="/api/admin", tags=["admin"])

_TOKEN_SALT = "genmedia-sxs-v3"

# Module-level dependency singletons (avoid function calls in arg defaults).
_Settings = Depends(get_settings_dep)
_AdminTokenHeader = Header(default=None)


def _admin_token(settings: Settings) -> str | None:
    """Stateless admin token derived from admin_pass; None if unset."""
    if not settings.admin_pass:
        return None
    raw = f"{_TOKEN_SALT}:{settings.admin_user}:{settings.admin_pass}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def require_admin(
    x_admin_token: str | None = _AdminTokenHeader,
    settings: Settings = _Settings,
) -> None:
    """Gate mutating/expensive endpoints behind admin login."""
    expected = _admin_token(settings)
    if not expected:
        raise HTTPException(status_code=500, detail="ADMIN_PASS not configured on server")
    if not x_admin_token or not hmac.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=401, detail="Admin authentication required")


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def admin_login(
    creds: LoginRequest,
    settings: Settings = _Settings,
) -> dict:
    if not settings.admin_pass:
        raise HTTPException(status_code=500, detail="ADMIN_PASS not configured")
    if creds.username == settings.admin_user and creds.password == settings.admin_pass:
        return {"status": "success", "token": _admin_token(settings)}
    raise HTTPException(status_code=401, detail="Invalid credentials")


@router.get("/whoami", dependencies=[Depends(require_admin)])
def whoami(settings: Settings = _Settings) -> dict:
    return {"user": settings.admin_user, "admin": True}
