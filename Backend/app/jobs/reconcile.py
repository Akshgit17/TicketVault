"""
Daily reconciliation.

Tests prove the code does what we think. Reconciliation catches the cases we
did not think of: a webhook that never arrived, a transfer that succeeded at
Razorpay after our process died, a partial refund recorded twice.

It reports; it does not self-heal. Automatic correction of money movements
hides the bug that caused the drift.
"""
import logging

from app.database import supabase
from app.services import ledger
from app.services.payments import to_paise

logger = logging.getLogger(__name__)


def find_discrepancies(limit: int = 500) -> dict:
    """
    Cross-check booking state against the ledger.

    Returns a report of everything that does not add up.
    """
    issues: list[dict] = []

    bookings = (
        supabase.table("bookings")
        .select("*")
        .in_("payment_status", ["paid", "refunded"])
        .limit(limit)
        .execute()
    ).data or []

    for booking in bookings:
        booking_id = booking["id"]
        entries = ledger.entries_for_booking(booking_id)
        totals = ledger.totals_by_kind(entries)
        expected = to_paise(booking["total_price"])

        # 1. A paid booking must have a capture entry for the right amount.
        captured = totals.get(ledger.KIND_CAPTURE, 0)
        if captured != expected:
            issues.append({
                "type": "capture_mismatch",
                "booking_id": booking_id,
                "expected_paise": expected,
                "ledger_paise": captured,
                "detail": "Booking is settled but the ledger capture does not match.",
            })

        # 2. Outflows must never exceed inflows, counting the deposit that
        #    funded them.
        #
        #    This used to sum booking-scoped rows only, which reported a false
        #    negative on EVERY forfeited booking: the deposit arrives tagged to
        #    the listing, while the compensation paid out of it is tagged to
        #    the booking, so the check saw the outflow and missed its source.
        #    A reconciliation job that alerts on every unhappy path is one
        #    nobody reads on the day it matters.
        balance = ledger.settlement_balance_paise(booking_id, booking.get("listing_id"))
        if balance < 0:
            issues.append({
                "type": "negative_balance",
                "booking_id": booking_id,
                "balance_paise": balance,
                "detail": "More money left this booking than entered it.",
            })

        # 2b. Each scope must also hold on its own, so a genuine error in the
        #     deposit cannot be masked by an offsetting one in the booking.
        listing_id = booking.get("listing_id")
        if listing_id:
            deposit_balance = ledger.deposit_balance_paise(listing_id)
            if deposit_balance < 0:
                issues.append({
                    "type": "negative_deposit_balance",
                    "booking_id": booking_id,
                    "listing_id": listing_id,
                    "balance_paise": deposit_balance,
                    "detail": "More left the deposit than was ever collected.",
                })

        # 3. A refunded booking must have refund entries covering the capture.
        if booking["payment_status"] == "refunded":
            refunded = totals.get(ledger.KIND_REFUND, 0)
            if refunded != captured:
                issues.append({
                    "type": "refund_mismatch",
                    "booking_id": booking_id,
                    "captured_paise": captured,
                    "refunded_paise": refunded,
                    "detail": "Booking is marked refunded but the amounts disagree.",
                })

    # 4. Payouts with no corresponding ledger entry, and vice versa.
    issues.extend(_orphaned_payouts())

    # 5. Money taken but never settled — the failure webhooks were meant to fix.
    issues.extend(_stuck_pending_bookings())

    report = {
        "checked_bookings": len(bookings),
        "issue_count": len(issues),
        "issues": issues,
    }

    if issues:
        logger.error(
            "Reconciliation found %d discrepancies", len(issues),
            extra={"issue_count": len(issues)},
        )
    else:
        logger.info(
            "Reconciliation clean across %d bookings", len(bookings),
            extra={"checked_bookings": len(bookings)},
        )

    return report


def _orphaned_payouts() -> list[dict]:
    payouts = (
        supabase.table("payouts").select("*").eq("status", "paid").execute()
    ).data or []

    issues = []
    for payout in payouts:
        entries = ledger.entries_for_booking(payout["booking_id"])
        paid_out = sum(
            int(e["amount_paise"]) for e in entries if e["kind"] == ledger.KIND_PAYOUT
        )
        if paid_out != int(payout["net_paise"]):
            issues.append({
                "type": "payout_not_in_ledger",
                "booking_id": payout["booking_id"],
                "payout_paise": int(payout["net_paise"]),
                "ledger_paise": paid_out,
                "detail": "A payout was marked paid but the ledger disagrees.",
            })
    return issues


def _stuck_pending_bookings() -> list[dict]:
    """
    Bookings with a Razorpay order that never reached a terminal state.

    Usually means a webhook was missed. Each one is potentially a customer who
    paid and got nothing.
    """
    pending = (
        supabase.table("bookings")
        .select("id, razorpay_order_id, created_at")
        .eq("payment_status", "pending")
        .execute()
    ).data or []

    return [
        {
            "type": "stuck_pending",
            "booking_id": b["id"],
            "order_id": b.get("razorpay_order_id"),
            "detail": "Order created but never settled — check Razorpay for a captured payment.",
        }
        for b in pending
        if b.get("razorpay_order_id")
    ]
