"""
Price guidance endpoint.

Public and read-only: the sell page needs a band before the seller has
committed to anything, and gating it behind auth would mean the anchor appears
after they have already typed a number — which is exactly backwards. Anchor
first and most sellers accept the anchor; show an empty field and they anchor
on hope.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.database import supabase
from app.middleware.auth import get_current_user
from app.services import pricing
from app.services.payments import to_paise
from app.services.user_service import get_user_by_clerk_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/pricing", tags=["pricing"])

UTC = timezone.utc


@router.get("/suggest")
def suggest_price(
    face_value: float = Query(..., gt=0, description="Ticket face value in rupees"),
    event_id: str | None = None,
    proposed_price: float | None = Query(None, gt=0),
):
    """
    A recommended band, a live sell probability, and the hard cap.

    Never returns an error for pricing reasons — if the model is unavailable
    the response degrades to rule-based guidance and says so in `source`.
    """
    face_paise = to_paise(face_value)
    context = _event_context(event_id) if event_id else {}

    try:
        result = pricing.suggest(
            face_value_paise=face_paise,
            proposed_price_paise=to_paise(proposed_price) if proposed_price else None,
            **context,
        )
    except Exception:
        # Belt and braces. pricing.suggest is written not to raise, but this
        # endpoint sits in front of a form field — it must not 500 whatever
        # happens inside.
        logger.exception("Pricing suggestion failed entirely; returning the cap only")
        cap = pricing.price_cap_paise(face_paise)
        result = {
            "p25_paise": int(face_paise * 0.9),
            "p50_paise": face_paise,
            "p75_paise": min(int(face_paise * 1.1), cap),
            "cap_paise": cap,
            "sell_probability": None,
            "source": "face_value",
            "model_version": None,
            "deposit_rate": None,
        }

    result["event_id"] = event_id
    return result


class LogRecommendationRequest(BaseModel):
    event_id: str | None = None
    face_value: float
    p25: float | None = None
    p50: float | None = None
    p75: float | None = None
    cap: float
    sell_probability: float | None = None
    source: str
    model_version: str | None = None
    chosen_price: float
    listing_id: str | None = None


@router.post("/recommendations", status_code=201)
def log_recommendation(
    body:   LogRecommendationRequest,
    claims: dict = Depends(get_current_user),
):
    """
    Record what we suggested and what the seller actually chose.

    This is the future training set, the live calibration check (does a
    predicted 80% really sell 80% of the time?), and the evidence that guidance
    changes behaviour. It is also the only thing in this system that cannot be
    back-filled — a recommendation not logged the day it was shown is gone.

    Deliberately never fatal to the caller: failing to log must not stop
    someone from listing a ticket.
    """
    user = get_user_by_clerk_id(claims["sub"])

    p25 = to_paise(body.p25) if body.p25 else None
    p75 = to_paise(body.p75) if body.p75 else None
    chosen = to_paise(body.chosen_price)

    try:
        row = supabase.table("pricing_recommendations").insert({
            "event_id":           body.event_id,
            "seller_id":          user["id"],
            "listing_id":         body.listing_id,
            "face_value_paise":   to_paise(body.face_value),
            "p25_paise":          p25,
            "p50_paise":          to_paise(body.p50) if body.p50 else None,
            "p75_paise":          p75,
            "cap_paise":          to_paise(body.cap),
            "sell_probability":   body.sell_probability,
            "source":             body.source,
            "model_version":      body.model_version,
            "chosen_price_paise": chosen,
            # "Accepted" means they landed inside the band we showed — the
            # measure of whether the guidance actually moved behaviour.
            "accepted":           (p25 <= chosen <= p75) if (p25 and p75) else None,
        }).execute()
    except Exception:
        logger.exception("Could not log a pricing recommendation")
        return {"status": "not_logged"}

    return {"status": "logged", "id": row.data[0]["id"] if row.data else None}


def _event_context(event_id: str) -> dict:
    """
    Pull demand features for an event.

    Returns {} on any failure, which drops `suggest` onto its own defaults —
    the cold-start path. The likeliest cause is not an unknown artist but the
    mundane stuff: a missing popularity tier, a brand new venue, a lookup that
    timed out.
    """
    try:
        res = (
            supabase.table("events")
            .select("id, date, popularity_tier, cities(city_tier)")
            .eq("id", event_id)
            .execute()
        )
        if not res.data:
            return {}
        event = res.data[0]

        days = None
        if event.get("date"):
            parsed = datetime.fromisoformat(str(event["date"]).replace("Z", "+00:00"))
            days = max(0, (parsed - datetime.now(UTC)).days)

        competing = (
            supabase.table("listings")
            .select("id", count="exact")
            .eq("event_id", event_id)
            .eq("status", "active")
            .limit(1)
            .execute()
        )

        city = event.get("cities") or {}
        return {
            "days_until_event":   days,
            "popularity_tier":    event.get("popularity_tier"),
            "city_tier":          city.get("city_tier") if isinstance(city, dict) else None,
            "is_weekend":         parsed.weekday() >= 4 if event.get("date") else None,
            "competing_listings": competing.count or 0,
        }
    except Exception:
        logger.exception("Could not load pricing context for event %s", event_id)
        return {}
