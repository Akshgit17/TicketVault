from fastapi import HTTPException
from app.database import supabase


def get_user_record(clerk_id: str) -> dict:
    """
    Like get_user_by_clerk_id, but includes the authorisation flag.

    Kept separate rather than widening the select on the existing function:
    that one is called on nearly every authenticated path, and admin state is
    only needed by the handful of routes that gate on it.
    """
    r = (
        supabase.table("users")
        .select("id, name, email, is_admin")
        .eq("clerk_id", clerk_id)
        .execute()
    )
    if not r.data:
        raise HTTPException(
            status_code=404,
            detail="User not found in Supabase. Please ensure POST /users/me was called after login.",
        )
    return r.data[0]


def get_user_by_clerk_id(clerk_id: str) -> dict:
    """
    Fetch user from Supabase 'users' table using Clerk ID.
    Raises 404 if not found.
    """
    r = supabase.table("users").select("id, name, email").eq("clerk_id", clerk_id).execute()
    if not r.data:
        raise HTTPException(
            status_code=404, 
            detail="User not found in Supabase. Please ensure POST /users/me was called after login."
        )
    return r.data[0]
