"""Admin authentication — a stateless token derived from ADMIN_PASS.

`image_routes`, `tts_routes` and `intake_routes` each mirror this rather than
importing it, so that a modality router stays independently importable; the
token itself is identical, so one login works everywhere.
"""

import hashlib
import hmac
import os
from typing import Optional

from dotenv import load_dotenv
from fastapi import Header, HTTPException

load_dotenv()


ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS")
_ADMIN_TOKEN_SALT = "project-pulse-sxs:v1"


def _admin_token() -> Optional[str]:
    """Stateless admin token derived from ADMIN_PASS. None if unset."""
    if not ADMIN_PASS:
        return None
    return hashlib.sha256(f"{_ADMIN_TOKEN_SALT}:{ADMIN_USER}:{ADMIN_PASS}".encode()).hexdigest()


async def require_admin(x_admin_token: str = Header(None)):
    """FastAPI dependency: gate mutating/expensive endpoints behind admin login."""
    expected = _admin_token()
    if not expected:
        raise HTTPException(status_code=500, detail="ADMIN_PASS not configured on server")
    if not x_admin_token or not hmac.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=401, detail="Admin authentication required")
