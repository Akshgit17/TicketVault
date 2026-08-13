import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, HttpUrl

from app.database import supabase
from app.middleware.auth import get_current_user
from app.services.user_service import get_user_by_clerk_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/events", tags=["events"])


@router.get("")
def list_events(
    city_id:      str | None = None,
    city_slug:    str | None = None,
    q:            str | None = Query(None, description="Free-text search over title and venue"),
    include_past: bool = False,
    with_availability: bool = Query(
        False, description="Include listing_count and from_price per event"
    ),
    limit:        int = Query(24, ge=1, le=100),
    offset:       int = Query(0, ge=0),
):
    """
    Public endpoint — no auth required.

    Past events are excluded by default. Previously this served every event
    regardless of date, so the catalogue filled with concerts that had already
    happened and could never be fulfilled.
    """
    query = (
        supabase.table("events")
        .select("*, cities(id, name, slug)")
        .order("date", desc=False)
        .order("title", desc=False)
    )

    # A cancelled show can never be delivered, so it must not be browsable at
    # all. Unlike the past-event filter there is no `include_cancelled` escape
    # here: the admin route lists everything, and no public caller has a reason
    # to see one.
    query = query.is_("cancelled_at", "null")

    if not include_past:
        query = query.gte("date", datetime.now(timezone.utc).isoformat())

    if city_id:
        query = query.eq("city_id", city_id)
    elif city_slug:
        city_res = (
            supabase.table("cities")
            .select("id")
            .eq("slug", city_slug)
            .eq("is_active", True)
            .execute()
        )
        if city_res.data:
            query = query.eq("city_id", city_res.data[0]["id"])

    if q:
        # Escape PostgREST's `or` list separators so a comma or paren in the
        # search box cannot restructure the filter expression.
        safe = q.replace(",", " ").replace("(", " ").replace(")", " ").strip()
        if safe:
            query = query.or_(f"title.ilike.%{safe}%,venue.ilike.%{safe}%")

    events = query.range(offset, offset + limit - 1).execute().data or []

    if with_availability and events:
        _attach_availability(events)

    return events


def _attach_availability(events: list[dict]) -> None:
    """
    Add `listing_count` and `from_price` to each event, in place.

    Browsing concerts and browsing tickets are different things. A concert with
    nothing listed is still worth showing, because a seller may arrive
    tomorrow, but a buyer deserves to know before they click. Without this the
    catalogue looks identical whether every show is sold out or nothing has
    ever been listed.

    One extra query for the whole page rather than one per event. At this
    catalogue size that is cheaper than a PostgREST embedded aggregate, and it
    does not depend on the join being spelled exactly right.
    """
    ids = [e["id"] for e in events]
    try:
        rows = (
            supabase.table("listings")
            .select("event_id, price")
            .in_("event_id", ids)
            .eq("status", "active")
            .execute()
        ).data or []
    except Exception:
        logger.exception("Could not load listing availability")
        rows = []

    counts: dict[str, int] = {}
    cheapest: dict[str, float] = {}
    for row in rows:
        eid = row["event_id"]
        counts[eid] = counts.get(eid, 0) + 1
        price = float(row["price"])
        if eid not in cheapest or price < cheapest[eid]:
            cheapest[eid] = price

    for event in events:
        event["listing_count"] = counts.get(event["id"], 0)
        event["from_price"] = cheapest.get(event["id"])


# ---------------------------------------------------------------------------
# Seller-submitted event requests
#
# Sellers cannot insert into `events` directly. The catalogue is the trust
# surface: a seller who can create arbitrary events can invent one that does
# not exist, list a ticket against it, and take money for something nobody can
# verify. Admin approval is the control — see Database/migrations/006.
# ---------------------------------------------------------------------------


class EventRequestBody(BaseModel):
    title:        str = Field(min_length=3, max_length=160)
    venue:        str = Field(min_length=2, max_length=160)
    city_id:      str
    date:         datetime
    image_url:    HttpUrl | None = None
    evidence_url: HttpUrl | None = Field(
        None, description="Link proving the event exists — booking page, announcement"
    )
    notes:        str | None = Field(None, max_length=1000)


@router.post("/requests", status_code=201)
def create_event_request(
    body:   EventRequestBody,
    claims: dict = Depends(get_current_user),
):
    """Seller proposes an event that is not yet in the catalogue."""
    user = get_user_by_clerk_id(claims["sub"])

    if body.date <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="That date is in the past.")

    city = supabase.table("cities").select("id").eq("id", body.city_id).execute()
    if not city.data:
        raise HTTPException(status_code=400, detail="Unknown city.")

    payload = {
        "requester_id": user["id"],
        "title":        body.title.strip(),
        "venue":        body.venue.strip(),
        "city_id":      body.city_id,
        "date":         body.date.isoformat(),
        "image_url":    str(body.image_url) if body.image_url else None,
        "evidence_url": str(body.evidence_url) if body.evidence_url else None,
        "notes":        body.notes,
    }

    try:
        result = supabase.table("event_requests").insert(payload).execute()
    except Exception as e:
        # The partial unique index rejects a duplicate while one is pending.
        if "uq_event_request_pending" in str(e):
            raise HTTPException(
                status_code=409,
                detail="You've already requested this event. It's awaiting review.",
            )
        logger.error("Event request insert failed: %s", e)
        raise HTTPException(status_code=500, detail="Could not submit your request.")

    logger.info("Event request submitted: user_id=%s title=%s", user["id"], body.title)
    return result.data[0]


@router.get("/requests/mine")
def my_event_requests(claims: dict = Depends(get_current_user)):
    """The caller's own requests, so they can see review progress."""
    user = get_user_by_clerk_id(claims["sub"])
    result = (
        supabase.table("event_requests")
        .select("*, cities(id, name, slug)")
        .eq("requester_id", user["id"])
        .order("created_at", desc=True)
        .execute()
    )
    return result.data or []


@router.get("/{event_id}")
def get_event(event_id: str):
    """
    Public endpoint, no auth required.

    A cancelled or finished event is still returned rather than 404'd, with
    flags the page uses to explain itself. Someone following an old link
    deserves "this show was cancelled" rather than a dead end that looks like
    the site is broken. Selling and buying are blocked at their own endpoints,
    so showing the page is safe.
    """
    result = (
        supabase.table("events")
        .select("*, cities(id, name, slug)")
        .eq("id", event_id)
        .execute()
    )
    # Avoid .single() — it raises 406 when no row is found.
    if not result.data:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found")

    event = result.data[0]
    event_date = _parse_ts(event.get("date"))
    event["is_cancelled"] = bool(event.get("cancelled_at"))
    event["is_past"] = bool(event_date and event_date <= datetime.now(timezone.utc))
    event["is_sellable"] = not event["is_cancelled"] and not event["is_past"]
    return event


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
