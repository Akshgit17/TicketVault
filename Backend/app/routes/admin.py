"""
Admin surface: catalogue moderation and the event-request approval queue.

Every route here depends on `require_admin`, which reads the flag from the
database rather than from a token claim. Non-admins get 404 rather than 403 so
the existence of this surface is not confirmed to them.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.database import supabase
from app.middleware.auth import require_admin
from app.services import deposits, fulfillment, refunds
from app.services.payments import to_paise

logger = logging.getLogger(__name__)
UTC = timezone.utc
router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


# --- overview --------------------------------------------------------------


@router.get("/stats")
def stats():
    """Counts for the admin overview. Cheap head-only queries, no row fetch."""

    def count(table: str, **filters) -> int:
        q = supabase.table(table).select("id", count="exact")
        for col, val in filters.items():
            q = q.eq(col, val)
        res = q.limit(1).execute()
        return res.count or 0

    now = datetime.now(timezone.utc).isoformat()
    upcoming = (
        supabase.table("events")
        .select("id", count="exact")
        .gte("date", now)
        .limit(1)
        .execute()
    )

    return {
        "pending_event_requests": count("event_requests", status="pending"),
        "upcoming_events":        upcoming.count or 0,
        "active_listings":        count("listings", status="active"),
        "total_users":            count("users"),
    }


# --- event request queue ---------------------------------------------------


class ReviewBody(BaseModel):
    review_note: str | None = Field(None, max_length=1000)


@router.get("/event-requests")
def list_event_requests(
    status: str = Query("pending", pattern="^(pending|approved|rejected|all)$"),
):
    q = (
        supabase.table("event_requests")
        .select("*, cities(id, name, slug), users!event_requests_requester_id_fkey(id, name, email)")
        .order("created_at", desc=True)
    )
    if status != "all":
        q = q.eq("status", status)
    return q.limit(200).execute().data or []


@router.post("/event-requests/{request_id}/approve")
def approve_event_request(
    request_id: str,
    admin: dict = Depends(require_admin),
):
    """
    Approve a request and create the real catalogue event.

    Guarded on `status = 'pending'` so a double-click or a replayed call cannot
    create the same event twice.
    """
    req = supabase.table("event_requests").select("*").eq("id", request_id).execute()
    if not req.data:
        raise HTTPException(status_code=404, detail="Request not found")
    request = req.data[0]

    if request["status"] != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"This request was already {request['status']}.",
        )

    try:
        created = (
            supabase.table("events")
            .insert({
                "title":      request["title"],
                "venue":      request["venue"],
                "city_id":    request["city_id"],
                "date":       request["date"],
                "image_url":  request["image_url"],
                "source":     "seller_request",
                "created_by": request["requester_id"],
            })
            .execute()
        )
        event_id = created.data[0]["id"]
    except Exception as e:
        # uq_event (title, city_id, date) — the event already exists, which is
        # a valid outcome: link the request to it instead of failing.
        if "uq_event" in str(e):
            existing = (
                supabase.table("events")
                .select("id")
                .eq("title", request["title"])
                .eq("city_id", request["city_id"])
                .eq("date", request["date"])
                .execute()
            )
            if not existing.data:
                raise HTTPException(status_code=500, detail="Could not create the event.")
            event_id = existing.data[0]["id"]
        else:
            logger.error("Event creation failed for request %s: %s", request_id, e)
            raise HTTPException(status_code=500, detail="Could not create the event.")

    updated = (
        supabase.table("event_requests")
        .update({
            "status":      "approved",
            "event_id":    event_id,
            "reviewed_by": admin["id"],
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", request_id)
        .eq("status", "pending")
        .execute()
    )
    if not updated.data:
        raise HTTPException(status_code=409, detail="This request was reviewed by someone else.")

    logger.info("Event request approved: request_id=%s event_id=%s admin=%s",
                request_id, event_id, admin["id"])
    return updated.data[0]


@router.post("/event-requests/{request_id}/reject")
def reject_event_request(
    request_id: str,
    body:  ReviewBody,
    admin: dict = Depends(require_admin),
):
    """
    Reject with a reason. The reason is shown to the seller — a rejection
    without one produces a support message instead of a fixed resubmission.
    """
    if not body.review_note or not body.review_note.strip():
        raise HTTPException(status_code=400, detail="Give the seller a reason for the rejection.")

    updated = (
        supabase.table("event_requests")
        .update({
            "status":      "rejected",
            "review_note": body.review_note.strip(),
            "reviewed_by": admin["id"],
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", request_id)
        .eq("status", "pending")
        .execute()
    )
    if not updated.data:
        raise HTTPException(status_code=409, detail="Request not found, or already reviewed.")

    logger.info("Event request rejected: request_id=%s admin=%s", request_id, admin["id"])
    return updated.data[0]


# --- catalogue and transaction views ---------------------------------------


@router.get("/events")
def list_all_events(limit: int = Query(200, ge=1, le=500), offset: int = Query(0, ge=0)):
    """Unlike the public route, this includes past and cancelled events."""
    events = (
        supabase.table("events")
        .select("*, cities(id, name, slug)")
        .order("date", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    ).data or []

    if events:
        _attach_event_counts(events)
    return events


def _attach_event_counts(events: list[dict]) -> None:
    """
    How much is riding on each event, so an admin can see the blast radius
    before touching anything.
    """
    ids = [e["id"] for e in events]
    try:
        listings = (
            supabase.table("listings")
            .select("id, event_id, status")
            .in_("event_id", ids)
            .execute()
        ).data or []
    except Exception:
        logger.exception("Could not load listing counts for admin events")
        listings = []

    active: dict[str, int] = {}
    sold: dict[str, int] = {}
    for l in listings:
        if l["status"] == "active":
            active[l["event_id"]] = active.get(l["event_id"], 0) + 1
        elif l["status"] == "sold":
            sold[l["event_id"]] = sold.get(l["event_id"], 0) + 1

    for e in events:
        e["active_listings"] = active.get(e["id"], 0)
        e["sold_listings"] = sold.get(e["id"], 0)


class UpdateEventRequest(BaseModel):
    title:              str | None = Field(None, min_length=3, max_length=160)
    venue:              str | None = Field(None, min_length=2, max_length=160)
    city_id:            str | None = None
    date:               datetime | None = None
    image_url:          str | None = None
    popularity_tier:    int | None = Field(None, ge=1, le=5)
    transfer_supported: bool | None = None


@router.patch("/events/{event_id}")
def update_event(
    event_id: str,
    body:  UpdateEventRequest,
    admin: dict = Depends(require_admin),
):
    """
    Correct or reschedule a concert.

    Moving the date is treated as a POSTPONEMENT, not a new event: the original
    date is preserved in `postponed_from` so buyers can be shown what changed.
    Existing bookings are deliberately left alone. BookMyShow and District
    honour tickets for a rescheduled show, so cancelling everyone's purchase
    because a promoter moved a date would destroy valid sales and refund people
    who still want to go. A buyer who no longer wants the new date can report a
    problem, which routes to the dispute queue where a human decides.
    """
    existing = supabase.table("events").select("*").eq("id", event_id).execute()
    if not existing.data:
        raise HTTPException(404, "Event not found")
    event = existing.data[0]

    if event.get("cancelled_at"):
        raise HTTPException(409, "This event is cancelled and cannot be edited.")

    updates: dict = {}
    for field in ("title", "venue", "image_url", "popularity_tier", "transfer_supported"):
        value = getattr(body, field)
        if value is not None:
            updates[field] = value

    if body.city_id and body.city_id != event["city_id"]:
        if not supabase.table("cities").select("id").eq("id", body.city_id).execute().data:
            raise HTTPException(400, "Unknown city.")
        updates["city_id"] = body.city_id

    postponed = False
    if body.date is not None:
        new_date = body.date
        old_date = _parse(event.get("date"))
        if old_date is None or abs((new_date - old_date).total_seconds()) > 60:
            updates["date"] = new_date.isoformat()
            # Only record the FIRST original date. Rescheduling twice should
            # still show where the show started, not the previous guess.
            if not event.get("postponed_from") and old_date:
                updates["postponed_from"] = old_date.isoformat()
            postponed = True

    if not updates:
        return event

    updated = (
        supabase.table("events").update(updates).eq("id", event_id).execute()
    )
    if not updated.data:
        raise HTTPException(409, "Could not update the event.")

    logger.info(
        "Event %s updated by admin %s (%s)%s",
        event_id, admin["id"], ", ".join(sorted(updates)),
        " [POSTPONED]" if postponed else "",
        extra={"event_id": event_id, "postponed": postponed},
    )
    return updated.data[0]


class CancelEventRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.get("/events/{event_id}/cancel-impact")
def cancel_impact(event_id: str):
    """
    What cancelling would actually do, before anyone commits to it.

    Refunding a room full of buyers is not something to discover the
    consequences of afterwards.
    """
    listings = (
        supabase.table("listings")
        .select("id, status, deposit_paid_paise, deposit_returned_at, deposit_forfeited_at")
        .eq("event_id", event_id)
        .execute()
    ).data or []

    bookings = []
    if listings:
        bookings = (
            supabase.table("bookings")
            .select("id, total_price, payment_status, fulfillment_status")
            .in_("listing_id", [l["id"] for l in listings])
            .execute()
        ).data or []

    refundable = [
        b for b in bookings
        if b["payment_status"] == "paid"
        and b.get("fulfillment_status") != fulfillment.RELEASED
    ]
    already_paid_out = [
        b for b in bookings if b.get("fulfillment_status") == fulfillment.RELEASED
    ]
    deposits_to_return = [
        l for l in listings
        if l.get("deposit_paid_paise")
        and not l.get("deposit_returned_at")
        and not l.get("deposit_forfeited_at")
    ]

    return {
        "listings_total":           len(listings),
        "listings_live":            len([l for l in listings if l["status"] == "active"]),
        "bookings_to_refund":       len(refundable),
        "refund_total_paise":       sum(to_paise(b["total_price"]) for b in refundable),
        "deposits_to_return":       len(deposits_to_return),
        "deposit_total_paise":      sum(int(l["deposit_paid_paise"]) for l in deposits_to_return),
        # Money that has already left. Cancelling cannot claw it back, and the
        # admin should know that before pressing the button rather than after.
        "already_paid_out":         len(already_paid_out),
    }


@router.post("/events/{event_id}/cancel")
def cancel_event(
    event_id: str,
    body:  CancelEventRequest,
    admin: dict = Depends(require_admin),
):
    """
    Call off a concert: refund every buyer, return every deposit, withdraw
    every listing.

    THE SELLER IS NOT AT FAULT. A promoter cancelling a show is nothing to do
    with the person reselling a ticket to it, so deposits are RETURNED and not
    forfeited. Treating this like a failed transfer would fine sellers for
    something outside their control, and is the single most important thing to
    get right on this path.

    Bookings already released are skipped. That money has left the platform and
    there is no honest way to reverse it from here.
    """
    existing = supabase.table("events").select("*").eq("id", event_id).execute()
    if not existing.data:
        raise HTTPException(404, "Event not found")
    event = existing.data[0]

    if event.get("cancelled_at"):
        return {"status": "already_cancelled", "event_id": event_id}

    listings = (
        supabase.table("listings").select("*").eq("event_id", event_id).execute()
    ).data or []

    refunded, deposits_returned, skipped, failures = [], [], [], []

    for listing in listings:
        bookings = (
            supabase.table("bookings")
            .select("*")
            .eq("listing_id", listing["id"])
            .eq("payment_status", "paid")
            .execute()
        ).data or []

        for booking in bookings:
            if booking.get("fulfillment_status") == fulfillment.RELEASED:
                # Already paid out to the seller. Nothing to reverse.
                skipped.append(booking["id"])
                continue
            try:
                refunds.refund_booking(booking, reason="event_cancelled")
                refunded.append(booking["id"])
                try:
                    fulfillment.fail_fulfillment(
                        booking, reason=f"event cancelled: {body.reason[:120]}",
                        actor="admin", actor_id=admin["id"],
                    )
                except fulfillment.FulfillmentError:
                    # Already terminal, or an invalid transition. The refund is
                    # what matters and it has happened.
                    pass
            except Exception as e:
                logger.exception(
                    "Could not refund booking %s on event cancellation", booking["id"],
                    extra={"booking_id": booking["id"], "alert": True},
                )
                failures.append({"booking_id": booking["id"], "error": str(e)[:200]})

        # Give the deposit back. Not a forfeit: the seller did nothing wrong.
        if listing.get("fee_razorpay_payment_id") and not deposits.is_resolved(listing):
            try:
                deposits.return_deposit(listing, reason="event_cancelled")
                deposits_returned.append(listing["id"])
            except Exception as e:
                logger.exception(
                    "Could not return deposit for listing %s on event cancellation",
                    listing["id"],
                    extra={"listing_id": listing["id"], "alert": True},
                )
                failures.append({"listing_id": listing["id"], "error": str(e)[:200]})

        supabase.table("listings").update({
            "status": "cancelled", "locked_by": None, "lock_expiry": None,
        }).eq("id", listing["id"]).not_.in_("status", ["cancelled"]).execute()

    marked = (
        supabase.table("events")
        .update({
            "cancelled_at":        datetime.now(UTC).isoformat(),
            "cancellation_reason": body.reason.strip(),
        })
        .eq("id", event_id)
        .is_("cancelled_at", "null")
        .execute()
    )
    if not marked.data:
        return {"status": "already_cancelled", "event_id": event_id}

    logger.warning(
        "Event %s cancelled by admin %s: %d refunded, %d deposits returned, "
        "%d already paid out, %d failures",
        event_id, admin["id"], len(refunded), len(deposits_returned),
        len(skipped), len(failures),
        extra={"event_id": event_id, "alert": bool(failures)},
    )
    return {
        "status":            "cancelled",
        "event_id":          event_id,
        "refunded":          refunded,
        "deposits_returned": deposits_returned,
        "already_paid_out":  skipped,
        "failures":          failures,
    }


def _parse(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@router.get("/listings")
def list_all_listings(
    status: str | None = None,
    limit:  int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    q = (
        supabase.table("listings")
        .select("*, events(id, title, date, venue), users(id, name, email)")
        .order("created_at", desc=True)
    )
    if status:
        q = q.eq("status", status)
    return q.range(offset, offset + limit - 1).execute().data or []


# --- dispute queue --------------------------------------------------------
#
# A dispute freezes the seller's payout, and until now nothing could unfreeze
# it short of editing the database. That made a false claim an effective way to
# stall an honest seller indefinitely, which is a worse problem than the
# dispute itself. This is the resolution path.


@router.get("/disputes")
def list_disputes():
    """
    Everything an admin needs to decide, on one screen.

    The two signals that actually decide most cases:

      seller_provided_proof   Seller has evidence and the buyer disputes it:
                              genuinely contested, read both sides. No proof at
                              all: the buyer's account is the only account there
                              is, and upholding is usually right.

      buyer_prior_disputes    A first dispute is unremarkable. A fourth from the
                              same account is the story.
    """
    rows = (
        supabase.table("bookings")
        .select(
            "*, listings(id, price, seller_id, deposit_paid_paise, "
            "events(id, title, date, venue))"
        )
        .eq("confirmation_status", "disputed")
        # An upheld dispute keeps confirmation_status = disputed as its record,
        # so terminal bookings must be excluded or resolved disputes would
        # never leave the queue.
        .not_.in_("fulfillment_status", list(fulfillment.TERMINAL))
        .order("created_at", desc=True)
        .limit(200)
        .execute()
    ).data or []

    if not rows:
        return []

    buyer_ids = {r["user_id"] for r in rows if r.get("user_id")}
    seller_ids = {
        (r.get("listings") or {}).get("seller_id")
        for r in rows if (r.get("listings") or {}).get("seller_id")
    }

    people = (
        supabase.table("users")
        .select("id, name, email")
        .in_("id", list(buyer_ids | seller_ids))
        .execute()
    ).data or []
    by_id = {p["id"]: p for p in people}

    # One query for every buyer's dispute history, rather than one per row.
    history = (
        supabase.table("bookings")
        .select("user_id")
        .in_("user_id", list(buyer_ids))
        # Deliberately NOT filtered to open disputes. History is the point: a
        # buyer with three prior claims is the signal, whether those claims
        # were upheld or rejected.
        .eq("confirmation_status", "disputed")
        .execute()
    ).data or []
    dispute_counts: dict[str, int] = {}
    for h in history:
        dispute_counts[h["user_id"]] = dispute_counts.get(h["user_id"], 0) + 1

    out = []
    for r in rows:
        listing = r.get("listings") or {}
        out.append({
            "booking_id":            r["id"],
            "event":                 (listing.get("events") or {}).get("title"),
            "event_date":            (listing.get("events") or {}).get("date"),
            "total_price":           r.get("total_price"),
            "fulfillment_status":    r.get("fulfillment_status"),
            "payment_status":        r.get("payment_status"),
            "created_at":            r.get("created_at"),
            "buyer":                 by_id.get(r.get("user_id")),
            "seller":                by_id.get(listing.get("seller_id")),
            "listing_id":            listing.get("id"),
            "deposit_paise":         listing.get("deposit_paid_paise"),
            "seller_provided_proof": bool(r.get("transfer_proof_url")),
            "transfer_proof_url":    r.get("transfer_proof_url"),
            # Includes this one, so a first-time reporter reads as 1.
            "buyer_prior_disputes":  dispute_counts.get(r.get("user_id"), 1),
        })
    return out


class ResolveDisputeRequest(BaseModel):
    # uphold = the buyer was right. reject = the claim is not supported.
    resolution:  str = Field(pattern="^(uphold|reject)$")
    note:        str = Field(min_length=3, max_length=1000)


@router.post("/disputes/{booking_id}/resolve")
def resolve_dispute(
    booking_id: str,
    body:  ResolveDisputeRequest,
    admin: dict = Depends(require_admin),
):
    """
    Close a dispute one way or the other.

    UPHOLD  the buyer is refunded and compensated from the seller's forfeited
            deposit, and the listing returns to needing a new deposit. Exactly
            the same treatment as a missed deadline, because the outcome for
            the buyer is the same: they paid and did not get a usable ticket.

    REJECT  the freeze lifts and the payout proceeds on the next job run.

    Both require a note. An unexplained resolution is unauditable, and this is
    the one place in the system where a human overrides the state machine.
    """
    r = (
        supabase.table("bookings")
        .select("*, listings(*)")
        .eq("id", booking_id)
        .execute()
    )
    if not r.data:
        raise HTTPException(404, "Booking not found")
    booking = r.data[0]

    if booking.get("confirmation_status") != "disputed":
        raise HTTPException(409, "This booking is not under dispute.")

    listing = booking.get("listings") or {}
    note = body.note.strip()

    # `confirmation_status` is a Postgres ENUM: pending, confirmed,
    # auto_confirmed, disputed. There is no "resolved" member, and inventing
    # one here previously made this endpoint fail on its very last statement,
    # AFTER the refund, the forfeit and the listing reset had all committed.
    # The money moved and the dispute stayed open.
    #
    # So resolution is expressed through the states that already exist:
    #
    #   uphold  the booking moves to a TERMINAL fulfilment state (failed), and
    #           the queue excludes terminal bookings. confirmation_status stays
    #           `disputed`, which is the truth: it was disputed, and the
    #           outcome lives in booking_events.
    #   reject  the claim did not stand, so the booking returns to `confirmed`
    #           and the payout resumes.
    if body.resolution == "uphold":
        try:
            fulfillment.fail_fulfillment(
                booking,
                reason=f"dispute upheld by admin: {note[:200]}",
                actor="admin",
                actor_id=admin["id"],
            )
        except fulfillment.FulfillmentError as e:
            raise HTTPException(409, e.message)

        try:
            refunds.refund_booking(booking, reason="dispute_upheld")
        except refunds.RefundError as e:
            # The state has already moved, so surface the failure loudly
            # rather than leaving a booking that looks resolved but is not.
            logger.error(
                "Dispute upheld but refund failed for booking %s: %s",
                booking_id, e.message,
                extra={"booking_id": booking_id, "alert": True},
            )
            raise HTTPException(502, f"Refund failed: {e.message}")

        if listing:
            try:
                deposits.forfeit_deposit(listing, booking, reason="dispute_upheld")
            except Exception:
                logger.exception(
                    "Could not forfeit deposit on upheld dispute %s", booking_id,
                    extra={"booking_id": booking_id, "alert": True},
                )

            # Same policy as an SLA breach: off the market until a fresh
            # deposit backs it.
            supabase.table("listings").update({
                "status":                   "pending_fee",
                "locked_by":                None,
                "lock_expiry":              None,
                "deposit_paid_paise":       None,
                "deposit_forfeited_at":     None,
                "deposit_forfeit_reason":   None,
                "fee_razorpay_payment_id":  None,
            }).eq("id", listing["id"]).eq("status", "sold").execute()

        # Left as `disputed`. fail_fulfillment above already moved the booking
        # to a terminal state, which is what removes it from the queue.
        pass
    else:
        # Clearing the flag is what lets release_due_escrow pick it up again.
        supabase.table("bookings").update({
            "confirmation_status": "confirmed",
        }).eq("id", booking_id).eq("confirmation_status", "disputed").execute()

    supabase.table("booking_events").insert({
        "booking_id":  booking_id,
        "from_status": booking.get("fulfillment_status"),
        "to_status":   booking.get("fulfillment_status"),
        "actor":       "admin",
        "actor_id":    admin["id"],
        "reason":      f"dispute {body.resolution}: {note[:400]}",
    }).execute()

    logger.info(
        "Dispute %s on booking %s by admin %s", body.resolution, booking_id, admin["id"],
        extra={"booking_id": booking_id, "resolution": body.resolution},
    )
    return {"status": body.resolution, "booking_id": booking_id}


@router.get("/bookings")
def list_all_bookings(
    status: str | None = None,
    limit:  int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    q = (
        supabase.table("bookings")
        .select("*, listings(id, price, events(id, title, date))")
        .order("created_at", desc=True)
    )
    if status:
        q = q.eq("status", status)
    return q.range(offset, offset + limit - 1).execute().data or []
