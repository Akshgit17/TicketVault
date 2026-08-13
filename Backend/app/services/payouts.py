"""
Seller payouts via Razorpay Route.

Before this existed, buyer money arrived in the platform account and stopped
there — `auto_confirm.py` carried the comment "in a real system, you'd trigger
a payout to the seller here". This is that.

⚠️  NOT YET VERIFIED AGAINST LIVE RAZORPAY ROUTE.
    Route requires marketplace onboarding (Phase 0.3) which is still pending.
    The ledger, fee arithmetic, idempotency and state transitions are covered by
    tests; the single `client.transfer.create` call is written to Razorpay's
    documented shape but has never executed against the real API. Treat that one
    call as unproven until a sandbox transfer succeeds.

WHEN payouts fire is deliberately not decided here — the escrow release trigger
(T+24h after the event) lands in Phase 3.7. This module only answers "how".
"""
import logging
from datetime import datetime, timezone

from postgrest.exceptions import APIError

from app.config import SELLER_SUCCESS_FEE_RATE, SIMULATE_PAYOUTS
from app.database import supabase
from app.services import ledger
from app.services.payments import to_paise
from app.services.razorpay import client

logger = logging.getLogger(__name__)

UTC = timezone.utc


class PayoutError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def compute_split(gross_paise: int) -> tuple[int, int]:
    """
    Split a captured amount into (seller_net, platform_fee), both paise.

    Rounding always favours the seller by at most one paise, and the two parts
    are guaranteed to sum to the gross — never derive one of them separately.
    """
    fee = int(gross_paise * SELLER_SUCCESS_FEE_RATE)
    net = gross_paise - fee
    if net <= 0:
        raise PayoutError("fee_exceeds_gross", "Fee would consume the entire payout.")
    return net, fee


def release_payout(booking: dict, listing: dict) -> dict:
    """
    Pay the seller for a settled booking. Idempotent per booking.

    Callers must have confirmed the booking is genuinely due — this function
    checks payment state but not fulfilment.
    """
    booking_id = booking["id"]

    if booking.get("payment_status") != "paid":
        raise PayoutError(
            "not_payable",
            f"Booking is {booking.get('payment_status')}, not paid.",
        )

    seller_id = listing["seller_id"]
    seller = _load_seller(seller_id)

    if seller.get("payout_hold"):
        raise PayoutError("on_hold", "Seller payouts are on hold pending review.")

    linked_account = seller.get("razorpay_linked_account_id")
    if not linked_account and not SIMULATE_PAYOUTS:
        raise PayoutError(
            "no_linked_account",
            "Seller has no payout account configured.",
        )

    gross = to_paise(booking["total_price"])
    net, fee = compute_split(gross)

    # The UNIQUE constraint on payouts.booking_id is what actually prevents
    # paying a seller twice — not this check, which only races.
    try:
        created = supabase.table("payouts").insert({
            "booking_id":  booking_id,
            "seller_id":   seller_id,
            "gross_paise": gross,
            "fee_paise":   fee,
            "net_paise":   net,
            "status":      "processing",
        }).execute()
    except APIError as e:
        if "uq_payout_booking" in str(e) or "duplicate key" in str(e).lower():
            logger.info("Payout for booking %s already exists; skipping", booking_id)
            return {"status": "already_paid", "booking_id": booking_id}
        raise

    payout_row = created.data[0]

    if SIMULATE_PAYOUTS:
        # Route is unavailable (see config.SIMULATE_PAYOUTS). Everything either
        # side of this line is real — the payout row, the split, the ledger
        # entries, the state transition. Only the outbound bank leg is stood
        # in for, and the `sim_` prefix makes that impossible to mistake for a
        # genuine Razorpay transfer id when reading the ledger later.
        transfer_id = f"sim_{booking_id[:18]}"
        logger.warning(
            "SIMULATED payout of %s paise to seller %s for booking %s — "
            "no money actually moved (SIMULATE_PAYOUTS is on)",
            net, seller_id, booking_id,
            extra={"booking_id": booking_id, "simulated": True},
        )
    else:
        try:
            transfer = client.transfer.create({
                "account":  linked_account,
                "amount":   net,
                "currency": "INR",
                "notes":    {"booking_id": booking_id},
            })
        except Exception as e:
            supabase.table("payouts").update({
                "status": "failed",
                "failure_reason": str(e)[:500],
            }).eq("id", payout_row["id"]).execute()
            logger.exception("Route transfer failed for booking %s", booking_id)
            raise PayoutError("transfer_failed", "Could not transfer funds to the seller.")

        transfer_id = transfer.get("id")

    supabase.table("payouts").update({
        "status":               "paid",
        "razorpay_transfer_id": transfer_id,
        "paid_at":              datetime.now(UTC).isoformat(),
    }).eq("id", payout_row["id"]).execute()

    ledger.record_payout(
        booking_id=booking_id,
        seller_id=seller_id,
        amount_paise=net,
        transfer_id=transfer_id,
    )
    if fee > 0:
        ledger.record_fee(
            booking_id=booking_id,
            amount_paise=fee,
            key_suffix=f"payout:{transfer_id}",
            listing_id=listing.get("id"),
        )

    logger.info(
        "Paid out %s paise to seller %s for booking %s", net, seller_id, booking_id,
        extra={"booking_id": booking_id, "net_paise": net, "fee_paise": fee},
    )

    return {
        "status":      "paid",
        "booking_id":  booking_id,
        "net_paise":   net,
        "fee_paise":   fee,
        "transfer_id": transfer_id,
    }


def _load_seller(seller_id: str) -> dict:
    r = supabase.table("users").select("*").eq("id", seller_id).execute()
    if not r.data:
        raise PayoutError("no_seller", "Seller not found.")
    return r.data[0]
