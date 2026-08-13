import logging
import time

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

bearer = HTTPBearer()

# Cached with a TTL. Previously this cached forever, so a Clerk signing-key
# rotation meant every request failed authentication until the process was
# restarted.
JWKS_TTL_SECONDS = 3600
_jwks_cache: dict | None = None
_jwks_fetched_at: float = 0.0


async def _fetch_jwks() -> dict:
    url = f"{settings.CLERK_JWT_ISSUER}/.well-known/jwks.json"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def _get_jwks(force_refresh: bool = False) -> dict:
    global _jwks_cache, _jwks_fetched_at

    fresh = _jwks_cache and (time.monotonic() - _jwks_fetched_at) < JWKS_TTL_SECONDS
    if fresh and not force_refresh:
        return _jwks_cache

    try:
        _jwks_cache = await _fetch_jwks()
        _jwks_fetched_at = time.monotonic()
    except Exception as e:
        # Serve a stale key set rather than failing every request outright —
        # an expired cache is far better than an auth outage.
        if _jwks_cache:
            logger.warning("JWKS refresh failed (%s); serving cached keys", e)
            return _jwks_cache
        raise

    return _jwks_cache


async def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
) -> dict:
    token = creds.credentials
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")

        jwks = await _get_jwks()
        key = next((k for k in jwks["keys"] if k["kid"] == kid), None)

        if not key:
            # Unknown kid usually means Clerk rotated keys. Refresh once before
            # rejecting, rather than failing until the cache happens to expire.
            jwks = await _get_jwks(force_refresh=True)
            key = next((k for k in jwks["keys"] if k["kid"] == kid), None)

        if not key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid signing key",
            )
        payload = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=settings.CLERK_JWT_ISSUER,
            options={"verify_aud": False},
        )
        return payload
    except JWTError as e:
        # Reason goes to the logs, not to the caller — the specific failure
        # ("signature expired" vs "bad audience") is useful to an attacker.
        logger.info("Token rejected: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed.",
        )


def require_admin(claims: dict = Depends(get_current_user)) -> dict:
    """
    Gate for every /admin route. Returns the caller's user row.

    Admin status is read from the database, never from a token claim — Clerk
    metadata is editable from the frontend session in some configurations, and
    a role that can be set by the client is not a role. Declared `def` rather
    than `async def` so the blocking Supabase call runs in the threadpool
    instead of on the event loop, consistent with the rest of the codebase.
    """
    # Imported here to keep this module importable without a configured
    # database, which the auth unit tests rely on.
    from app.services.user_service import get_user_record

    user = get_user_record(claims["sub"])
    if not user.get("is_admin"):
        # 404, not 403: a non-admin should not be able to confirm that an
        # admin surface exists at this path.
        logger.warning("Non-admin hit an admin route: user_id=%s", user.get("id"))
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return user
