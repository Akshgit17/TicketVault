from fastapi import HTTPException
from app.database import supabase

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
