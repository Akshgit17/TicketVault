import logging
from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel, Field

from app.middleware.auth import get_current_user
from app.services.user_service import get_user_by_clerk_id
from app.database import supabase
from app.services.razorpay import create_order
from app.services.payments import (
    PaymentVerificationError,
    to_paise,
    verify_payment_for,
)
from app.services.settlement import SettlementError, fail_booking, settle_booking
from app.services import fulfillment
from app.config import settings, RESERVATION_MINUTES

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/bookings", tags=["bookings"])
UTC = timezone.utc


def _parse_event_date(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _extract_signed_url(result: object) -> str | None:
    """Handle supabase-py signed URL response shape differences."""
    if isinstance(result, dict):
        return result.get("signedURL") or result.get("signedUrl")
    return (
        getattr(result, "signedURL", None)
        or getattr(result, "signedUrl", None)
        or getattr(result, "signed_url", None)
    )




# ── SCHEMAS ───────────────────────────────────────────────────────────────────

class InitiateBookingRequest(BaseModel):
    listing_id:  str
    quantity:    int = 1
    buyer_name:  str
    buyer_email: str
    buyer_phone: str


class VerifyPaymentRequest(BaseModel):
    booking_id:           str
    razorpay_order_id:    str
    razorpay_payment_id:  str
    razorpay_signature:   str


class ConfirmBookingRequest(BaseModel):
    booking_id: str


class DisputeBookingRequest(BaseModel):
    booking_id: str
    reason:     str


class MarkTransferredRequest(BaseModel):
    booking_id: str
    proof_url:  str | None = None


class TransferMobileRequest(BaseModel):
    booking_id: str
    # Indian mobile, with or without +91. Kept loose deliberately — a rejected
    # valid number blocks the only route to fulfilment.
    mobile:     str = Field(min_length=10, max_length=16)
    consent:    bool


# ── STEP 1 — Initiate booking + create Razorpay order ────────────────────────

@router.post("/initiate")
def initiate_booking(
    body:   InitiateBookingRequest,
    claims: dict = Depends(get_current_user),
):
    buyer = get_user_by_clerk_id(claims["sub"])

    # Fetch listing
    r = (
        supabase.table("listings")
        .select("*, events(title, date, cancelled_at)")
        .eq("id", body.listing_id)
        .execute()
    )
    if not r.data:
        raise HTTPException(404, "Listing not found.")

    listing = r.data[0]

    if listing["status"] != "active":
        raise HTTPException(409, "This listing is no longer available.")

    # The concert must still be ahead of us and still happening.
    #
    # Hiding past and cancelled shows from the marketplace is not the same as
    # blocking a purchase. Someone with the page already open, a bookmark, or a
    # link shared an hour ago reaches this endpoint directly, and taking their
    # money for a show that has started or been called off produces a refund at
    # best and an angry buyer at worst. Checked here, immediately before the
    # money moves.
    event = listing.get("events") or {}
    if event.get("cancelled_at"):
        raise HTTPException(409, "That concert has been cancelled.")

    event_date = _parse_event_date(event.get("date"))
    if event_date and event_date <= datetime.now(UTC):
        raise HTTPException(409, "That concert has already started.")

    if listing["seller_id"] == buyer["id"]:
        raise HTTPException(400, "You cannot buy your own listing.")

    if body.quantity > listing["quantity"]:
        raise HTTPException(400, f"Only {listing['quantity']} ticket(s) available.")

    total = float(listing["price"]) * body.quantity

    # Lock listing atomically (only if still active)
    now         = datetime.now(UTC)
    # Reservations are now actively released by the fulfilment cron, so the
    # window can be generous without stranding inventory.
    lock_expiry = now + timedelta(minutes=RESERVATION_MINUTES)

    lock_res = (
        supabase.table("listings")
        .update({
            "status":      "locked",
            "locked_by":   buyer["id"],
            "lock_expiry": lock_expiry.isoformat(),
        })
        .eq("id", body.listing_id)
        .eq("status", "active")          # atomic guard
        .execute()
    )

    if not lock_res.data:
        raise HTTPException(409, "Listing was just taken. Please try another.")

    # Create Razorpay order
    rz_order = create_order(
        amount_inr=total,
        receipt=f"tv_{body.listing_id[:8]}",
        notes={
            "listing_id": body.listing_id,
            "buyer_id":   buyer["id"],
        },
    )

    # Create booking record (pending)
    booking_res = supabase.table("bookings").insert({
        "user_id":          buyer["id"],
        "listing_id":       body.listing_id,
        "quantity":         body.quantity,
        "total_price":      total,
        "payment_status":   "pending",
        "razorpay_order_id": rz_order["id"],
        "buyer_name":       body.buyer_name,
        "buyer_email":      body.buyer_email,
        "buyer_phone":      body.buyer_phone,
    }).execute()

    booking = booking_res.data[0]

    return {
        "booking_id":        booking["id"],
        "razorpay_order_id": rz_order["id"],
        "razorpay_key_id":   settings.RAZORPAY_KEY_ID,
        "amount":            total,
        "currency":          "INR",
        "lock_expiry":       lock_expiry.isoformat(),
    }


# ── STEP 2 — Verify Razorpay payment ─────────────────────────────────────────

@router.post("/verify-payment")
def verify_booking_payment(
    body:   VerifyPaymentRequest,
    claims: dict = Depends(get_current_user),
):
    buyer = get_user_by_clerk_id(claims["sub"])

    # Fetch booking
    r = (
        supabase.table("bookings")
        # `listing_fee` was selected here and never read. Migration 012 drops
        # that generated column, and PostgREST errors on a select naming a
        # column that does not exist, so leaving it would have broken payment
        # verification the moment the migration ran.
        .select("*, listings(id, seller_id, price, quantity)")
        .eq("id", body.booking_id)
        .eq("user_id", buyer["id"])
        .execute()
    )
    if not r.data:
        raise HTTPException(404, "Booking not found.")

    booking = r.data[0]

    if booking["payment_status"] == "paid":
        return {"status": "already_paid", "booking_id": body.booking_id}

    # Verify the payment is genuine AND belongs to this booking, at this amount.
    try:
        verify_payment_for(
            expected_order_id=booking.get("razorpay_order_id"),
            expected_amount_paise=to_paise(booking["total_price"]),
            razorpay_order_id=body.razorpay_order_id,
            razorpay_payment_id=body.razorpay_payment_id,
            razorpay_signature=body.razorpay_signature,
        )
    except PaymentVerificationError as e:
        # A transient provider outage must not release the listing or fail the
        # booking — the buyer may legitimately retry, and the webhook will
        # settle it regardless.
        if e.code != "verification_unavailable":
            fail_booking(booking, e.code, "client")
        raise HTTPException(400, e.message)

    # Settlement is shared with the webhook path so the two cannot diverge.
    try:
        return settle_booking(booking, body.razorpay_payment_id, "client")
    except SettlementError as e:
        raise HTTPException(409, e.message)


# ── GET my bookings ───────────────────────────────────────────────────────────

def _refund_summaries(booking_ids: list[str]) -> dict[str, dict]:
    """
    What each booking actually got back, keyed by booking id.

    Buyers could previously see that a transfer had failed but not what they
    were owed or whether it had been paid, which is the one thing they care
    about at that moment.

    Compensation is read from the ledger rather than the refunds table because
    it is not a refund: it is funded by the seller's forfeited deposit, and it
    is an obligation recorded rather than money moved (Razorpay will not refund
    more than was captured). `compensation_paid` says so honestly.
    """
    if not booking_ids:
        return {}

    out: dict[str, dict] = {}

    refunds = (
        supabase.table("refunds")
        .select("booking_id, amount_paise, status, razorpay_refund_id, processed_at")
        .in_("booking_id", booking_ids)
        .eq("status", "processed")
        .execute()
    ).data or []

    for row in refunds:
        entry = out.setdefault(row["booking_id"], {})
        entry["refunded_paise"] = entry.get("refunded_paise", 0) + int(row["amount_paise"])
        entry["razorpay_refund_id"] = row.get("razorpay_refund_id")
        entry["refunded_at"] = row.get("processed_at")
        # A real Razorpay refund, so it settles on the original card. Razorpay
        # quotes 5 to 7 working days; the buyer should be told that rather
        # than left wondering why the money has not appeared.
        entry["refund_is_real"] = True

    try:
        comps = (
            supabase.table("ledger_entries")
            .select("booking_id, amount_paise")
            .in_("booking_id", booking_ids)
            .eq("kind", "compensation")
            .execute()
        ).data or []
        for row in comps:
            entry = out.setdefault(row["booking_id"], {})
            entry["compensation_paise"] = (
                entry.get("compensation_paise", 0) + int(row["amount_paise"])
            )
            entry["compensation_paid"] = False
    except Exception:
        # Ledger unavailable is not a reason to fail the booking list.
        logger.exception("Could not load compensation entries")

    return out


@router.get("/my/all")
def my_bookings(claims: dict = Depends(get_current_user)):
    buyer = get_user_by_clerk_id(claims["sub"])

    r = (
        supabase.table("bookings")
        .select("""
            *,
            listings(
                id, price, quantity,
                events(title, date, venue, image_url),
                cities(name)
            )
        """)
        .eq("user_id", buyer["id"])
        .order("created_at", desc=True)
        .execute()
    )
    bookings = r.data or []

    summaries = _refund_summaries([b["id"] for b in bookings])
    for b in bookings:
        b["refund"] = summaries.get(b["id"])

    return bookings


# ── GET booking details ───────────────────────────────────────────────────────

@router.get("/{booking_id}")
def get_booking(
    booking_id: str,
    claims:     dict = Depends(get_current_user),
):
    buyer = get_user_by_clerk_id(claims["sub"])

    r = (
        supabase.table("bookings")
        .select("""
            *,
            listings(
                id, price, original_price, quantity, qr_image_url,
                events(title, date, venue, image_url),
                cities(name)
            )
        """)
        .eq("id", booking_id)
        .eq("user_id", buyer["id"])
        .execute()
    )

    if not r.data:
        raise HTTPException(404, "Booking not found.")

    booking = r.data[0]

    # Attach QR URL if paid.
    # Some historical rows may store a full public URL instead of storage path.
    if booking["payment_status"] == "paid":
        listing = booking.get("listings") or {}
        qr_path = listing.get("qr_image_url")
        if qr_path:
            try:
                if isinstance(qr_path, str) and qr_path.startswith(("http://", "https://")):
                    booking["qr_signed_url"] = qr_path
                else:
                    signed = supabase.storage.from_("ticket-qrs").create_signed_url(
                        qr_path, expires_in=3600
                    )
                    # No public-URL fallback: the ticket-qrs bucket is private,
                    # so a constructed public URL only yields a broken image.
                    booking["qr_signed_url"] = _extract_signed_url(signed)
            except Exception:
                booking["qr_signed_url"] = None

    booking["refund"] = _refund_summaries([booking_id]).get(booking_id)

    return booking


# ── CONFIRM / DISPUTE ─────────────────────────────────────────────────────────

@router.post("/confirm")
def confirm_booking(
    body:   ConfirmBookingRequest,
    claims: dict = Depends(get_current_user),
):
    """
    Buyer confirms the ticket arrived in their own BookMyShow/District account.

    This replaces the old "confirm within 2 hours" step, which only asked the
    buyer to acknowledge that they could see a QR image — and which auto-expired
    before a gate failure could possibly be discovered.
    """
    buyer = get_user_by_clerk_id(claims["sub"])
    booking = _load_own_booking(body.booking_id, buyer["id"])

    if booking["payment_status"] != "paid":
        raise HTTPException(400, "Booking not paid.")

    # Legacy QR bookings keep the old confirmation semantics.
    if booking.get("fulfillment_status", fulfillment.NOT_STARTED) == fulfillment.NOT_STARTED:
        if booking["confirmation_status"] != "pending":
            raise HTTPException(400, f"Already {booking['confirmation_status']}.")
        supabase.table("bookings").update({
            "confirmation_status": "confirmed",
        }).eq("id", body.booking_id).eq("confirmation_status", "pending").execute()
        return {"status": "confirmed", "booking_id": body.booking_id}

    try:
        fulfillment.confirm_transfer_received(booking, buyer["id"])
    except fulfillment.FulfillmentError as e:
        raise HTTPException(409, e.message)

    return {
        "status": "transfer_confirmed",
        "booking_id": body.booking_id,
        "escrow_release_at": booking.get("escrow_release_at"),
    }


@router.post("/transfer-mobile")
def set_transfer_mobile(
    body:   TransferMobileRequest,
    claims: dict = Depends(get_current_user),
):
    """
    Buyer supplies the mobile number registered with their ticketing app, and
    consents to it being shared with the seller.

    The transfer cannot happen without it — the seller types this number into
    BookMyShow/District to send the ticket. That makes it a hard requirement
    *and* a PII disclosure, so consent is explicit and timestamped rather than
    buried in terms.
    """
    if not body.consent:
        raise HTTPException(400, "We need your permission before sharing this with the seller.")

    digits = "".join(c for c in body.mobile if c.isdigit())
    if len(digits) < 10:
        raise HTTPException(400, "That doesn't look like a valid mobile number.")
    normalised = digits[-10:]

    buyer = get_user_by_clerk_id(claims["sub"])
    booking = _load_own_booking(body.booking_id, buyer["id"])

    if booking["payment_status"] != "paid":
        raise HTTPException(400, "Booking not paid.")

    updated = (
        supabase.table("bookings")
        .update({
            "buyer_platform_mobile": normalised,
            "mobile_consent_at":     datetime.now(UTC).isoformat(),
        })
        .eq("id", body.booking_id)
        .eq("user_id", buyer["id"])
        .execute()
    )
    if not updated.data:
        raise HTTPException(409, "Could not save that number.")

    logger.info("Transfer mobile recorded: booking_id=%s", body.booking_id)
    return {"status": "ok", "booking_id": body.booking_id}


@router.post("/mark-transferred")
def mark_transferred(
    body:   MarkTransferredRequest,
    claims: dict = Depends(get_current_user),
):
    """Seller states they have completed the issuer-side transfer."""
    seller = get_user_by_clerk_id(claims["sub"])

    r = (
        supabase.table("bookings")
        .select("*, listings(id, seller_id)")
        .eq("id", body.booking_id)
        .execute()
    )
    if not r.data:
        raise HTTPException(404, "Booking not found.")

    booking = r.data[0]
    listing = booking.get("listings") or {}
    if listing.get("seller_id") != seller["id"]:
        # Same shape as "not found" — do not confirm the booking exists to a
        # user who has no relationship with it.
        raise HTTPException(404, "Booking not found.")

    try:
        fulfillment.mark_transfer_initiated(booking, seller["id"], body.proof_url)
    except fulfillment.FulfillmentError as e:
        raise HTTPException(409, e.message)

    return {"status": "transfer_initiated", "booking_id": body.booking_id}


@router.post("/dispute")
def dispute_booking(
    body:   DisputeBookingRequest,
    claims: dict = Depends(get_current_user),
):
    """
    Buyer reports a problem.

    Open until escrow releases — i.e. past the event — because a ticket that
    fails at the gate cannot be discovered any earlier.
    """
    buyer = get_user_by_clerk_id(claims["sub"])
    booking = _load_own_booking(body.booking_id, buyer["id"])

    if booking["payment_status"] != "paid":
        raise HTTPException(400, "Booking not paid.")
    if not fulfillment.can_dispute(booking):
        raise HTTPException(400, "This booking is closed and can no longer be disputed.")
    if booking["confirmation_status"] == "disputed":
        return {"status": "disputed", "booking_id": body.booking_id}

    supabase.table("bookings").update({
        "confirmation_status": "disputed",
    }).eq("id", body.booking_id).execute()

    # How often has this buyer done this before?
    #
    # A dispute costs the buyer nothing and freezes a seller's money, so the
    # obvious abuse is a buyer who claims non-delivery on every purchase. There
    # is no dispute queue to adjudicate that, so the cheapest useful defence is
    # to make the pattern visible: a first dispute is unremarkable, a fourth
    # from the same account is the story.
    #
    # Counted rather than blocked on purpose. A buyer with a genuine second
    # problem must still be able to report it, and refusing them would punish
    # exactly the people the guarantee exists for.
    prior = _prior_dispute_count(buyer["id"], exclude_booking_id=body.booking_id)

    supabase.table("booking_events").insert({
        "booking_id":  body.booking_id,
        "from_status": booking.get("fulfillment_status"),
        "to_status":   booking.get("fulfillment_status"),
        "actor":       "buyer",
        "actor_id":    buyer["id"],
        "reason":      f"dispute ({prior} prior from this buyer): {body.reason[:400]}",
    }).execute()

    # Whether the seller supplied transfer evidence decides which way an admin
    # should lean. Seller has proof and the buyer disputes: genuinely contested,
    # needs a human. Seller has no proof: the buyer's account is the only
    # account there is.
    has_seller_proof = bool(booking.get("transfer_proof_url"))

    logger.warning(
        "Dispute filed on booking %s by buyer %s (%d prior disputes, "
        "seller_proof=%s)",
        body.booking_id, buyer["id"], prior, has_seller_proof,
        extra={
            "booking_id": body.booking_id,
            "buyer_id": buyer["id"],
            "prior_disputes": prior,
            "seller_provided_proof": has_seller_proof,
            "alert": prior >= 2,
        },
    )
    return {
        "status":     "disputed",
        "booking_id": body.booking_id,
        # Told plainly so the buyer knows a human is now involved and the
        # money is not simply gone.
        "payout_frozen": True,
    }


def _prior_dispute_count(buyer_id: str, exclude_booking_id: str) -> int:
    """
    Disputes this buyer has filed on other bookings.

    Best effort. A counting failure must never stop someone reporting a real
    problem, so it returns 0 rather than raising.
    """
    try:
        rows = (
            supabase.table("bookings")
            .select("id")
            .eq("user_id", buyer_id)
            .eq("confirmation_status", "disputed")
            .neq("id", exclude_booking_id)
            .execute()
        ).data or []
        return len(rows)
    except Exception:
        logger.exception("Could not count prior disputes for buyer %s", buyer_id)
        return 0


def _load_own_booking(booking_id: str, user_id: str) -> dict:
    r = (
        supabase.table("bookings")
        .select("*")
        .eq("id", booking_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not r.data:
        raise HTTPException(404, "Booking not found.")
    return r.data[0]
