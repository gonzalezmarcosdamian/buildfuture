"""
Supabase JWT auth dependency.
Supabase uses ES256 — verifies via JWKS endpoint.
Falls back to SEED_USER_ID in local dev (no SUPABASE_URL set).
"""
import os
import logging
import httpx
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

load_dotenv()

logger = logging.getLogger("buildfuture.auth")

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
DEV_USER_ID  = os.getenv("SEED_USER_ID", "00000000-0000-0000-0000-000000000001")

_bearer = HTTPBearer(auto_error=False)
_jwks_cache: list | None = None


def _get_jwks() -> list[dict]:
    global _jwks_cache
    if _jwks_cache is not None:
        return _jwks_cache
    try:
        r = httpx.get(f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json", timeout=8)
        r.raise_for_status()
        _jwks_cache = r.json().get("keys", [])
        logger.info("JWKS loaded: %d key(s)", len(_jwks_cache))
        return _jwks_cache
    except Exception as e:
        logger.error("Failed to load JWKS from Supabase: %s", e)
        return []


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """
    Returns the user_id (Supabase UUID).
    - Production: verifies JWT via Supabase JWKS (ES256), returns sub claim.
    - Dev (no SUPABASE_URL): returns DEV_USER_ID without any check.
    """
    if not SUPABASE_URL:
        logger.debug("Auth: dev mode, user=%s", DEV_USER_ID)
        return DEV_USER_ID

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header required",
        )

    token = credentials.credentials
    keys  = _get_jwks()

    if not keys:
        raise HTTPException(status_code=503, detail="Auth service temporarily unavailable")

    try:
        header = jwt.get_unverified_header(token)
        kid    = header.get("kid")
        key    = next((k for k in keys if k.get("kid") == kid), keys[0])

        payload = jwt.decode(
            token,
            key,
            algorithms=[header.get("alg", "ES256")],
            options={"verify_aud": False},
        )
        user_id: str | None = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token: no sub claim")
        return user_id
    except JWTError as e:
        logger.warning("JWT verification failed: %s", e)
        raise HTTPException(status_code=401, detail="Invalid or expired token")
