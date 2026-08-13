"""
The seller's security deposit.

A seller pays a refundable deposit to publish a listing. It has exactly two
possible endings, and never both:

    transfer completes  → returned in full, alongside the sale proceeds
    seller defaults     → forfeited: the buyer is compensated from it and the
                          platform retains the remainder

This is what makes the buyer guarantee *funded* rather than promised, and it is
the answer to "who pays when it goes wrong?" — the party who broke the deal.

Before this module the deposit was collected on every listing and returned on
no path at all, while the sell page told sellers they would get all of it back.

Every function here is idempotent. Both callers are background jobs that retry.
"""
import logging
from datetime import datetime, timezone

from app.config import LISTING_FEE_RATE, PLATFORM_FORFEIT_SHARE
from app.database import supabase
from app.services import ledger
from app.services.payments import to_paise
from app.services.razorpay import client

logger = logging.getLogger(__name__)

UTC = timezone.utc


class DepositError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def deposit_paise(listing: dict) -> int:
    """
    What the seller actually paid, in paise.

    Three sources, in descending order of authority:

      1. `deposit_paid_paise`  what was actually charged. Preferred over
         recomputing, because LISTING_FEE_RATE is a config value that can
         change and a deposit must be returned at the amount taken.
      2. `listing_fee`         the generated column, for rows read before
         migration 012 dropped it. Kept as a fallback rather than removed,
         because it costs one dict lookup and covers any row loaded from a
         database where 012 has not run yet.
      3. price × LISTING_FEE_RATE  computed.

    Step 3 is not redundant. This used to return 0 when the first two were
    absent, which is exactly the state a relisted listing is in after
    `_require_new_deposit` clears its deposit fields: the listing would then
    activate with a zero deposit and go back on sale backed by nothing,
    silently reopening the hole that requiring a new deposit exists to close.

    Zero is only correct when there is genuinely no price to compute from.
    """
    recorded = listing.get("deposit_paid_paise")
    if recorded:
        return int(recorded)

    fee = listing.get("listing_fee")
    if fee:
        return to_paise(fee)

    price = listing.get("price")
    if price:
        return int(round(to_paise(price) * LISTING_FEE_RATE))

    return 0


def is_resolved(listing: dict) -> bool:
    return bool(listing.get("deposit_returned_at") or listing.get("deposit_forfeited_at"))


# ── Capture ───────────────────────────────────────────────────────────────────

def record_deposit_paid(listing: dict, payment_id: str) -> dict:
    """
    Ledger the deposit at the moment the listing goes live.

    Called from settlement, which has already verified the payment with
    Razorpay. Failure here must not block activation — a missing ledger row is
    a reconciliation problem, whereas a listing that cannot activate is a
    seller who cannot sell.
    """
    listing_id = listing["id"]
    amount = deposit_paise(listing)

    if amount <= 0:
        # An unbacked listing: it can go on sale, but if the seller fails to
        # transfer there is nothing to compensate the buyer from. Alert-worthy
        # rather than merely notable.
        logger.error(
            "Listing %s is active with a ZERO deposit and is therefore unbacked",
            listing_id,
            extra={"listing_id": listing_id, "alert": True},
        )
        return {"status": "skipped", "reason": "zero_deposit"}

    supabase.table("listings").update({
        "deposit_paid_paise": amount,
    }).eq("id", listing_id).is_("deposit_paid_paise", "null").execute()

    ledger.record_deposit(
        listing_id=listing_id,
        seller_id=listing["seller_id"],
        amount_paise=amount,
        payment_id=payment_id,
    )
    return {"status": "recorded", "amount_paise": amount}


# ── Ending 1: return ──────────────────────────────────────────────────────────

def return_deposit(listing: dict, reason: str = "transfer_completed") -> dict:
    """
    Give the deposit back. Called when a booking reaches its released state.

    This is a real Razorpay refund against the deposit's own payment — the
    seller's money genuinely goes back to the card or account they paid from,
    which is why it needs no payout account and works today, unlike the sale
    proceeds.
    """
    listing_id = listing["id"]

    if listing.get("deposit_returned_at"):
        return {"status": "already_returned", "listing_id": listing_id}

    if listing.get("deposit_forfeited_at"):
        raise DepositError(
            "already_forfeited",
            "This deposit was forfeited and cannot be returned.",
        )

    amount = deposit_paise(listing)
    if amount <= 0:
        return {"status": "skipped", "reason": "zero_deposit"}

    payment_id = listing.get("fee_razorpay_payment_id")
    if not payment_id:
        raise DepositError("no_payment", "No deposit payment on file to refund.")

    try:
        rz_refund = client.payment.refund(payment_id, {
            "amount": amount,
            "speed": "normal",
            "notes": {"listing_id": listing_id, "reason": "deposit_return"},
        })
    except Exception as e:
        logger.exception("Deposit refund failed for listing %s", listing_id)
        raise DepositError("provider_failed", "The payment provider rejected the refund.")

    refund_id = rz_refund.get("id")

    # Guarded so two concurrent job runs cannot both claim the return.
    updated = (
        supabase.table("listings")
        .update({
            "deposit_returned_at": datetime.now(UTC).isoformat(),
            "deposit_refund_id":   refund_id,
        })
        .eq("id", listing_id)
        .is_("deposit_returned_at", "null")
        .execute()
    )
    if not updated.data:
        return {"status": "already_returned", "listing_id": listing_id}

    ledger.record_deposit_return(
        listing_id=listing_id,
        seller_id=listing["seller_id"],
        amount_paise=amount,
        refund_id=refund_id,
    )

    logger.info(
        "Returned deposit of %s paise for listing %s (%s)", amount, listing_id, reason,
        extra={"listing_id": listing_id, "amount_paise": amount, "refund_id": refund_id},
    )
    return {
        "status":       "returned",
        "listing_id":   listing_id,
        "amount_paise": amount,
        "refund_id":    refund_id,
    }


# ── Ending 2: forfeit ─────────────────────────────────────────────────────────

def forfeit_deposit(listing: dict, booking: dict, reason: str) -> dict:
    """
    Keep the deposit after a seller default, and pay part of it to the buyer.

    The deposit D is split by share, not computed from the ticket price:

        retained     = D × PLATFORM_FORFEIT_SHARE   → the platform
        compensation = D − retained                 → the buyer

    Splitting D directly means the two parts always sum to exactly D, and the
    buyer's share can never exceed what was actually collected.

    No money moves for the forfeiture itself: the deposit is already held, and
    the buyer's ticket refund is issued separately by the caller.

    ⚠️ THE COMPENSATION IS RECORDED, NOT DISBURSED.
    Razorpay will not refund more than was captured on a payment, so paying a
    buyer *extra* requires a real outbound transfer — which needs Razorpay
    Route, and Route onboarding requires a registered business entity this
    project does not have. The ledger entry is therefore an obligation the
    platform has incurred and can prove, not money that has landed. Settling it
    is a manual step.

    This is a deliberate, disclosed limitation rather than an oversight: the
    accounting is real and auditable, the disbursement rail is not available.
    Documented in docs/KNOWN_LIMITATIONS.md.
    """
    listing_id = listing["id"]

    if listing.get("deposit_forfeited_at"):
        return {"status": "already_forfeited", "listing_id": listing_id}

    if listing.get("deposit_returned_at"):
        raise DepositError(
            "already_returned",
            "This deposit was already returned and cannot be forfeited.",
        )

    amount = deposit_paise(listing)
    if amount <= 0:
        return {"status": "skipped", "reason": "zero_deposit"}

    # Split the deposit itself, rather than computing the buyer's share from
    # the ticket price. Two reasons this matters:
    #
    #   * it cannot over-pay. Half of the deposit is always within the deposit,
    #     so there is no path to compensating a buyer with money never
    #     collected, including when the seller repriced after paying.
    #   * the split stays 50/50 if the deposit rate is ever retuned, instead of
    #     silently sliding because two independent constants moved apart.
    #
    # `retained` is derived by subtraction so the two parts always sum to the
    # deposit exactly, with no rounding remainder left unaccounted for.
    retained = int(amount * PLATFORM_FORFEIT_SHARE)
    compensation = amount - retained

    updated = (
        supabase.table("listings")
        .update({
            "deposit_forfeited_at":   datetime.now(UTC).isoformat(),
            "deposit_forfeit_reason": reason[:500],
        })
        .eq("id", listing_id)
        .is_("deposit_forfeited_at", "null")
        .execute()
    )
    if not updated.data:
        return {"status": "already_forfeited", "listing_id": listing_id}

    if compensation > 0:
        ledger.record_compensation(
            listing_id=listing_id,
            booking_id=booking["id"],
            buyer_id=booking["user_id"],
            amount_paise=compensation,
            reason=reason,
        )
    if retained > 0:
        ledger.record_forfeit(
            listing_id=listing_id,
            booking_id=booking["id"],
            seller_id=listing["seller_id"],
            amount_paise=retained,
            reason=reason,
        )

    logger.info(
        "Forfeited deposit of %s paise on listing %s: %s to buyer, %s retained (%s)",
        amount, listing_id, compensation, retained, reason,
        extra={
            "listing_id": listing_id,
            "compensation_paise": compensation,
            "retained_paise": retained,
        },
    )
    return {
        "status":             "forfeited",
        "listing_id":         listing_id,
        "amount_paise":       amount,
        "compensation_paise": compensation,
        "retained_paise":     retained,
    }
