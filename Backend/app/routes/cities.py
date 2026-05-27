from fastapi import APIRouter
from app.database import supabase

router = APIRouter(prefix="/cities", tags=["cities"])


@router.get("")
async def list_cities(name: str | None = None):
    q = supabase.table("cities").select("*").eq("is_active", True)
    if name:
        q = q.eq("name", name)
    return q.execute().data
