from supabase import create_client
from scraper.config import SUPABASE_URL, SUPABASE_SERVICE_KEY

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
_city_cache: dict = {}


def get_city_id(canonical_name: str) -> str | None:
    if canonical_name in _city_cache:
        return _city_cache[canonical_name]
    r = (
        supabase.table("cities")
        .select("id")
        .eq("name", canonical_name)
        .eq("is_active", True)
        .single()
        .execute()
    )
    if r.data:
        _city_cache[canonical_name] = r.data["id"]
        return r.data["id"]
    return None


def upsert_event(event: dict):
    """Upsert on (name, city_id, date) — idempotent across scraper runs."""
    supabase.table("events").upsert(
        event,
        on_conflict="name,city_id,date",
    ).execute()
