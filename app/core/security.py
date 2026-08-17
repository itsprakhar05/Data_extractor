"""
app/core/security.py
---------------------
Verifies JWTs issued by auth_server.py, stateless (no DB round-trip).
Import get_current_user_id as a Depends() on every route that touches
the pipeline or user data.

Uses HTTPBearer (not OAuth2PasswordBearer) — Swagger's "Authorize"
dialog shows a plain "paste your token" field, since login itself
happens on a separate service (auth_server.py, port 8001), not here.

Requires AUTH_SECRET_KEY to be set to the SAME value used by
auth_server.py. The app refuses to start if it's missing — no silent
fallback to a default secret.
"""

import os
import logging

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

log = logging.getLogger("RAG_Pipeline")

ALGORITHM = "HS256"

SECRET_KEY = os.getenv("AUTH_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "AUTH_SECRET_KEY is not set. Refusing to start — the main app must "
        "share the same secret auth_server.py uses to sign tokens."
    )

bearer_scheme = HTTPBearer(auto_error=True)


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> str:
    """
    Decode + verify the bearer token. Returns the username (JWT 'sub' claim).
    Raises 401 on missing/invalid/expired token.
    """
    token = credentials.credentials
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str | None = payload.get("sub")
        if username is None:
            raise credentials_exception
        return username
    except JWTError as e:
        log.warning("[Auth] Token rejected: %s", e)
        raise credentials_exception