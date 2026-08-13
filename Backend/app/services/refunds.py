"""
Refunds.

One entry point, called from every path that needs to return money: fulfilment
SLA breach, dispute upheld, event cancelled, admin action. Centralised so the
ledger is always written and a booking can never be refunded twice.

Previously there was no refund code at all, while the sell page promised the
listing fee would be "fully refunded".
"""
import logging
from datetime import datetime, timezone

from postgrest.exceptions import APIError

from app.database import supabase
from app.services import ledger
from app.services.payments import to_paise
from app.services.razorpay import client

logger = logging.getLogger(__name__)

UTC = timezone.utc


class RefundError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def refund_booking(booking: dict, reason: str, amount_paise: int | None = None) -> dict:
    """
    Refund a paid booking, fully or partially.

    Idempotent: a booking already refunded returns the existing refund rather
    than issuing a second one.
    """
    booking_id = booking["id"]

    if booking.get("payment_status") == "refunded":
        existing = _existing_refund(booking_id)
        if existing:
            return {"status": "already_refunded", "refund_id": existing["id"]}

    if booking.get("payment_status") != "paid":
        raise RefundError(
            "not_refundable",
            f"Booking is {booking.get('payment_status')}, not paid.",
        )

    payment_id = booking.get("razorpay_payment_id")
    if not payment_id:
        raise RefundError("no_payment", "Booking has no payment to refund.")

    captured = to_paise(booking["total_price"])
    amount = amount_paise if amount_paise is not None else captured

    if amount <= 0 or amount > captured:
        raise RefundError(
            "invalid_amount",
            f"Refund of {amount} paise is not valid against a capture of {captured}.",
        )

    already = _refunded_total_paise(booking_id)
    if already + amount > captured:
        raise RefundError(
            "over_refund",
            f"Refunding {amount} would exceed the captured amount "
            f"({already} already refunded of {captured}).",
        )

    # Record intent before calling the provider. If the process dies mid-call,
    # a pending row remains and reconciliation can resolve it — rather than a
    # refund existing at Razorpay that we have no record of.
    try:
        pending = supabase.table("refunds").insert({
            "booking_id":   booking_id,
            "amount_paise": amount,
            "reason":       reason,
            "status":       "pending",
        }).execute()
    except APIError:
        logger.exception("Could not record refund intent for booking %s", booking_id)
        raise RefundError("record_failed", "Could not start the refund.")

    refund_row = pending.data[0]

    try:
        rz_refund = client.payment.refund(payment_id, {
            "amount": amount,
            "speed": "normal",
            "notes": {"booking_id": booking_id, "reason": reason[:200]},
        })
    except Exception as e:
        supabase.table("refunds").update({
            "status": "failed",
            "failure_reason": str(e)[:500],
        }).eq("id", refund_row["id"]).execute()
        logger.exception("Razorpay refund failed for booking %s", booking_id)
        raise RefundError("provider_failed", "The payment provider rejected the refund.")

    refund_id = rz_refund.get("id")

    supabase.table("refunds").update({
        "status":             "processed",
        "razorpay_refund_id": refund_id,
        "processed_at":       datetime.now(UTC).isoformat(),
    }).eq("id", refund_row["id"]).execute()

    ledger.record_refund(
        booking_id=booking_id,
        buyer_id=booking["user_id"],
        amount_paise=amount,
        refund_id=refund_id,
    )

    # Only a full refund flips the booking; a partial leaves it paid.
    if already + amount == captured:
        supabase.table("bookings").update({
            "payment_status": "refunded",
        }).eq("id", booking_id).eq("payment_status", "paid").execute()

    logger.info(
        "Refunded %s paise for booking %s (%s)", amount, booking_id, reason,
        extra={"booking_id": booking_id, "amount_paise": amount, "refund_id": refund_id},
    )

    return {
        "status":       "refunded",
        "refund_id":    refund_id,
        "amount_paise": amount,
        "booking_id":   booking_id,
    }


def _existing_refund(booking_id: str) -> dict | None:
    r = (
        supabase.table("refunds")
        .select("*")
        .eq("booking_id", booking_id)
        .eq("status", "processed")
        .execute()
    )
    return r.data[0] if r.data else None


def _refunded_total_paise(booking_id: str) -> int:
    r = (
        supabase.table("refunds")
        .select("amount_paise, status")
        .eq("booking_id", booking_id)
        .eq("status", "processed")
        .execute()
    )
    return sum(int(row["amount_paise"]) for row in (r.data or []))
