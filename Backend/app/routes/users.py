import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from app.middleware.auth import get_current_user
from app.database import supabase

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/users", tags=["users"])


class UpsertUserRequest(BaseModel):
    name: str
    email: EmailStr


@router.post("/me")
async def upsert_user(
    body: UpsertUserRequest,
    claims: dict = Depends(get_current_user),
):
    """Called on first sign-in to sync Clerk user into Supabase users table."""
    clerk_id = claims["sub"]
    logger.info(f"Upserting user: clerk_id={clerk_id}, email={body.email}")
    try:
        result = (
            supabase.table("users")
            .upsert(
                {"clerk_id": clerk_id, "name": body.name, "email": body.email},
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
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.get("/me")
async def get_me(claims: dict = Depends(get_current_user)):
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
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.get("/debug-token")
async def debug_token(claims: dict = Depends(get_current_user)):
    """Use this to verify JWT is being parsed correctly. Visit /users/debug-token with a Bearer token."""
    return {
        "clerk_id": claims.get("sub"),
        "email": claims.get("email"),
        "name": claims.get("name"),
        "all_claims": claims,
    }
