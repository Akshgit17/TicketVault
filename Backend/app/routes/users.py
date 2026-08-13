import logging
from fastapi import APIRouter, Depends, HTTPException
from app.middleware.auth import get_current_user
from app.database import supabase

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/users", tags=["users"])


def _identity_from_claims(claims: dict) -> tuple[str, str]:
    """
    Derive name and email from the verified Clerk token only.

    Previously these came from the request body, so any authenticated user could
    claim an arbitrary identity — and because users.email is UNIQUE, occupy
    another person's row. The client is not a trustworthy source for identity.
    """
    email = (
        claims.get("email")
        or claims.get("primary_email_address")
        or claims.get("email_address")
    )
    if not email:
        raise HTTPException(
            status_code=400,
            detail=(
                "Token does not contain an email claim. Add email to the Clerk "
                "JWT template so the backend can identify users."
            ),
        )

    name = (
        claims.get("name")
        or " ".join(p for p in [claims.get("first_name"), claims.get("last_name")] if p).strip()
        or email.split("@")[0]
    )
    return name, email


@router.post("/me")
def upsert_user(claims: dict = Depends(get_current_user)):
    """Called on first sign-in to sync the Clerk user into the Supabase users table."""
    clerk_id = claims["sub"]
    name, email = _identity_from_claims(claims)
    logger.info("Upserting user: clerk_id=%s", clerk_id)
    try:
        result = (
            supabase.table("users")
            .upsert(
                {"clerk_id": clerk_id, "name": name, "email": email},
                on_conflict="clerk_id",
            )
            .execute()
        )
        if not result.data:
            logger.error(f"Upsert returned no data for clerk_id={clerk_id}")
            raise HTTPException(status_code=500, detail="User upsert returned no data")
        logger.info(f"Upsert success: {result.data[0]}")
        return result.data[0]
    except Exception as e:
        logger.error(f"Failed to upsert user: {e}")
        raise HTTPException(status_code=500, detail="Could not load your profile.")


@router.get("/me")
def get_me(claims: dict = Depends(get_current_user)):
    clerk_id = claims["sub"]
    try:
        result = (
            supabase.table("users")
            .select("*")
            .eq("clerk_id", clerk_id)
            .single()
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="User not found in Supabase. Please ensure POST /users/me was called after login.")
        return result.data
    except Exception as e:
        logger.error(f"Error fetching user {clerk_id}: {e}")
        if "JSON object" in str(e) or "404" in str(e): # PostgREST 404 for .single()
             raise HTTPException(status_code=404, detail="User not found in Supabase.")
        raise HTTPException(status_code=500, detail="Could not load your profile.")


# NOTE: GET /users/debug-token was removed in Phase 1.4 — it returned the full
# decoded JWT claim set to any caller.
