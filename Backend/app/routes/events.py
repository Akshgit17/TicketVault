from fastapi import APIRouter, Depends, HTTPException
from app.database import supabase
from app.middleware.auth import get_current_user

router = APIRouter(prefix="/events", tags=["events"])


@router.get("")
async def list_events(
    city_id:  str | None = None,
    city_slug: str | None = None,
):
    """
    Public endpoint — no auth required.
    Fetch events, optionally filtered by city_id or city_slug.
    """
    q = (
        supabase.table("events")
        .select("*, cities(id, name, slug)")
        .order("date", desc=False)
        .order("title", desc=False)
    )

    if city_id:
        q = q.eq("city_id", city_id)

    elif city_slug:
        # Resolve slug → city_id first
        city_res = (
            supabase.table("cities")
            .select("id")
            .eq("slug", city_slug)
            .eq("is_active", True)
            .execute()
        )
        if city_res.data:
            q = q.eq("city_id", city_res.data[0]["id"])

    result = q.limit(50).execute()
    return result.data or []


@router.get("/{event_id}")
async def get_event(event_id: str):
    """
    Public endpoint — no auth required.
    Fetch a single event by UUID.
    """
    result = (
        supabase.table("events")
        .select("*, cities(id, name, slug)")
        .eq("id", event_id)
        .execute()
    )

    # Avoid .single() — it raises 406 when no row found
    if not result.data:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found")

    return result.data[0]
