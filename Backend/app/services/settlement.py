"""
Booking settlement.

Shared by the two paths that can settle a payment:
  - the client calling /bookings/verify-payment after the Razorpay modal closes
  - the Razorpay webhook (authoritative)

Both must produce the same end state, so the transition lives here once. Every
function is idempotent: whichever path arrives first wins, the second is a no-op.
"""
import logging
from datetime import datetime, timedelta, timezone

from postgrest.exceptions import APIError

from app.database import supabase
from app.services import ledger
from app.services.payments import to_paise

logger = logging.getLogger(__name__)

UTC = timezone.utc

# Retained from the original flow. Replaced by post-event escrow release in
# Phase 3 — deliberately not re-tuned here.
CONFIRMATION_WINDOW = timedelta(hours=2)


class SettlementError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def settle_booking(booking: dict, payment_id: str, source: str) -> dict:
    """
    Mark a booking paid and its listing sold, exactly once.

    `source` is only for logging — it records which path won the race.
    Returns {"status": "paid"|"already_paid", "booking_id": ...}.
    """
    booking_id = booking["id"]

    if booking.get("payment_status") == "paid":
        return {"status": "already_paid", "booking_id": booking_id}

    deadline = datetime.now(UTC) + CONFIRMATION_WINDOW

    try:
        settled = (
            supabase.table("bookings")
            .update({
                "payment_status":        "paid",
                "razorpay_payment_id":   payment_id,
                "confirmation_status":   "pending",
                "confirmation_deadline": deadline.isoformat(),
            })
            .eq("id", booking_id)
            .eq("payment_status", "pending")   # CAS: settle once
            .execute()
        )
    except APIError as e:
        # uq_bookings_razorpay_payment_id — this receipt already settled another
        # booking. The unique index is the last line of defence against replay.
        if "razorpay_payment_id" in str(e):
            raise SettlementError("payment_reused", "This payment has already been used.")
        raise

    if not settled.data:
        logger.info("Booking %s already settled before %s arrived", booking_id, source)
        return {"status": "already_paid", "booking_id": booking_id}

    supabase.table("listings").update({
        "status":      "sold",
        "locked_by":   None,
        "lock_expiry": None,
    }).eq("id", booking["listing_id"]).execute()

    # Record the inflow. Keyed on the payment id, so the client path and the
    # webhook path cannot both book it.
    #
    # Deliberately non-fatal: the booking is already settled by this point, and
    # the buyer's payment genuinely succeeded. Failing the request here would
    # tell a paying customer their payment failed, which is strictly worse than
    # an accounting gap. A missing entry is an incident, not a user-facing
    # error — reconciliation's `capture_mismatch` check exists to surface it.
    try:
        ledger.record_capture(
            booking_id=booking_id,
            buyer_id=booking["user_id"],
            amount_paise=to_paise(booking["total_price"]),
            payment_id=payment_id,
        )
    except Exception:
        logger.exception(
            "LEDGER WRITE FAILED for settled booking %s — reconcile manually",
            booking_id,
            extra={"booking_id": booking_id, "payment_id": payment_id, "alert": True},
        )

    # Start the transfer clock for transfer-enabled events. Non-fatal for the
    # same reason as the ledger write: the payment succeeded, and a fulfilment
    # bookkeeping failure must not be reported to the buyer as payment failure.
    try:
        _begin_fulfillment_if_supported(booking)
    except Exception:
        logger.exception(
            "Could not start fulfilment for settled booking %s", booking_id,
            extra={"booking_id": booking_id, "alert": True},
        )

    logger.info("Booking %s settled via %s", booking_id, source)
    return {
        "status":                "paid",
        "booking_id":            booking_id,
        "confirmation_deadline": deadline.isoformat(),
    }


def _begin_fulfillment_if_supported(booking: dict) -> None:
    """Look up the event behind this booking and start fulfilment if enabled."""
    from app.services import fulfillment

    listing_res = (
        supabase.table("listings")
        .select("event_id")
        .eq("id", booking["listing_id"])
        .execute()
    )
    if not listing_res.data:
        return

    event_res = (
        supabase.table("events")
        .select("*")
        .eq("id", listing_res.data[0]["event_id"])
        .execute()
    )
    if not event_res.data:
        return

    # Re-read the booking: settle_booking updated it, and the state machine
    # guards its transition on the current fulfillment_status.
    fresh = supabase.table("bookings").select("*").eq("id", booking["id"]).execute()
    if fresh.data:
        fulfillment.begin_fulfillment(
            fresh.data[0], event_res.data[0],
            buyer_mobile=booking.get("buyer_phone"),
        )


def fail_booking(booking: dict, reason: str, source: str) -> None:
    """
    Mark a booking failed and return its listing to the market.

    Guarded on `pending` so a late failure notification can never un-sell a
    booking that already settled.
    """
    booking_id = booking["id"]

    failed = (
        supabase.table("bookings")
        .update({"payment_status": "failed"})
        .eq("id", booking_id)
        .eq("payment_status", "pending")
        .execute()
    )

    if not failed.data:
        logger.info(
            "Ignoring failure for booking %s (%s via %s): no longer pending",
            booking_id, reason, source,
        )
        return

    supabase.table("listings").update({
        "status":      "active",
        "locked_by":   None,
        "lock_expiry": None,
    }).eq("id", booking["listing_id"]).eq("status", "locked").execute()

    logger.info("Booking %s failed (%s) via %s; listing released", booking_id, reason, source)


def activate_listing_after_fee(listing: dict, payment_id: str, source: str) -> dict:
    """Activate a listing once its fee is paid. Guarded on pending_fee."""
    listing_id = listing["id"]

    if listing.get("status") == "active":
        return {"status": "already_active", "listing_id": listing_id}

    activated = (
        supabase.table("listings")
        .update({"status": "active", "fee_razorpay_payment_id": payment_id})
        .eq("id", listing_id)
        .eq("status", "pending_fee")
        .execute()
    )

    if not activated.data:
        return {"status": "already_active", "listing_id": listing_id}

    # Ledger the deposit so it can be returned or forfeited later. Deliberately
    # non-fatal: a missing ledger row is a reconciliation problem, while a
    # listing that fails to activate is a seller who cannot sell. Same
    # degradation choice as the capture path above.
    try:
        from app.services import deposits
        deposits.record_deposit_paid(activated.data[0], payment_id)
    except Exception:
        logger.exception(
            "Could not ledger the deposit for listing %s; listing is active anyway",
            listing_id,
            extra={"listing_id": listing_id, "alert": True},
        )

    logger.info("Listing %s activated via %s", listing_id, source)
    return {"status": "active", "listing_id": listing_id}
