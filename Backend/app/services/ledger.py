"""
The money ledger.

Every rupee that moves gets a row. Append-only: corrections are new `reversal`
entries, never edits. All amounts are integer paise — money in floating point
accumulates error exactly where it is least acceptable.

Invariant worth holding onto: once a booking reaches a terminal state, its
entries net to zero.

    captured 50,000 in
    paid out 47,500 out
    fee       2,500 out
    ------------------------
    balance       0

A non-zero balance on a terminal booking means money is unaccounted for, which
is what `booking_balance_paise` and the reconciliation job in 2.5 look for.
"""
import logging

from postgrest.exceptions import APIError

from app.database import supabase

logger = logging.getLogger(__name__)

DIRECTION_IN = "in"
DIRECTION_OUT = "out"

KIND_CAPTURE = "capture"
KIND_PAYOUT = "payout"
KIND_REFUND = "refund"
KIND_FEE = "fee"
KIND_REVERSAL = "reversal"

# Deposit lifecycle (migration 010). These are listing-scoped rather than
# booking-scoped: the seller pays the deposit to publish a listing, long before
# any booking exists.
KIND_DEPOSIT = "deposit"
KIND_DEPOSIT_RETURN = "deposit_return"
KIND_FORFEIT = "forfeit"
KIND_COMPENSATION = "compensation"


def record(
    *,
    kind: str,
    direction: str,
    amount_paise: int,
    idempotency_key: str,
    booking_id: str | None = None,
    listing_id: str | None = None,
    user_id: str | None = None,
    external_ref: str | None = None,
    metadata: dict | None = None,
) -> dict | None:
    """
    Append one entry. Returns the row, or None if this movement was already
    recorded.

    `idempotency_key` must uniquely identify the *movement*, not the attempt —
    e.g. "capture:pay_abc123". A redelivered webhook or a retried job then
    produces no duplicate.
    """
    if amount_paise <= 0:
        raise ValueError(f"ledger amounts must be positive, got {amount_paise}")

    try:
        res = supabase.table("ledger_entries").insert({
            "booking_id":      booking_id,
            "listing_id":      listing_id,
            "user_id":         user_id,
            "direction":       direction,
            "kind":            kind,
            "amount_paise":    amount_paise,
            "external_ref":    external_ref,
            "idempotency_key": idempotency_key,
            "metadata":        metadata or {},
        }).execute()
    except APIError as e:
        if "idempotency" in str(e).lower() or "duplicate key" in str(e).lower():
            logger.info("Ledger entry %s already recorded; skipping", idempotency_key)
            return None
        raise

    logger.info(
        "Ledger %s %s %s paise", kind, direction, amount_paise,
        extra={
            "ledger_kind": kind,
            "amount_paise": amount_paise,
            "booking_id": booking_id,
            "idempotency_key": idempotency_key,
        },
    )
    return res.data[0] if res.data else None


# ── Typed helpers — the only ways money is allowed to move ────────────────────

def record_capture(booking_id: str, buyer_id: str, amount_paise: int, payment_id: str):
    """Buyer's money arrives in the platform account."""
    return record(
        kind=KIND_CAPTURE, direction=DIRECTION_IN, amount_paise=amount_paise,
        idempotency_key=f"capture:{payment_id}",
        booking_id=booking_id, user_id=buyer_id, external_ref=payment_id,
    )


def record_refund(booking_id: str, buyer_id: str, amount_paise: int, refund_id: str):
    """Money returned to the buyer."""
    return record(
        kind=KIND_REFUND, direction=DIRECTION_OUT, amount_paise=amount_paise,
        idempotency_key=f"refund:{refund_id}",
        booking_id=booking_id, user_id=buyer_id, external_ref=refund_id,
    )


def record_payout(booking_id: str, seller_id: str, amount_paise: int, transfer_id: str):
    """Money released to the seller."""
    return record(
        kind=KIND_PAYOUT, direction=DIRECTION_OUT, amount_paise=amount_paise,
        idempotency_key=f"payout:{transfer_id}",
        booking_id=booking_id, user_id=seller_id, external_ref=transfer_id,
    )


def record_fee(booking_id: str, amount_paise: int, key_suffix: str, listing_id: str | None = None):
    """Platform revenue retained from a booking."""
    return record(
        kind=KIND_FEE, direction=DIRECTION_OUT, amount_paise=amount_paise,
        idempotency_key=f"fee:{key_suffix}",
        booking_id=booking_id, listing_id=listing_id,
    )


def record_reversal(booking_id: str, amount_paise: int, direction: str, reason: str, key_suffix: str):
    """
    Correct an earlier entry without editing it.

    The original stays; the reversal offsets it. History remains auditable.
    """
    return record(
        kind=KIND_REVERSAL, direction=direction, amount_paise=amount_paise,
        idempotency_key=f"reversal:{key_suffix}",
        booking_id=booking_id, metadata={"reason": reason},
    )


# ── Deposit helpers (listing-scoped) ──────────────────────────────────────────
#
# A listing's deposit entries always net to zero once resolved:
#     returned:  +D −D                       = 0
#     forfeited: +D −compensation −forfeit    = 0
#
# The idempotency keys are derived from the listing, not from a payment or an
# attempt, because each of these can happen at most once per listing.

def record_deposit(listing_id: str, seller_id: str, amount_paise: int, payment_id: str):
    """Seller's security deposit captured; the listing goes live."""
    return record(
        kind=KIND_DEPOSIT, direction=DIRECTION_IN, amount_paise=amount_paise,
        idempotency_key=f"deposit:{payment_id}",
        listing_id=listing_id, user_id=seller_id, external_ref=payment_id,
    )


def record_deposit_return(listing_id: str, seller_id: str, amount_paise: int, refund_id: str):
    """Deposit returned in full after a completed transfer."""
    return record(
        kind=KIND_DEPOSIT_RETURN, direction=DIRECTION_OUT, amount_paise=amount_paise,
        idempotency_key=f"deposit_return:{listing_id}",
        listing_id=listing_id, user_id=seller_id, external_ref=refund_id,
    )


def record_forfeit(
    listing_id: str, booking_id: str, seller_id: str, amount_paise: int, reason: str
):
    """
    Portion of a forfeited deposit retained by the platform.

    Keyed on the BOOKING, not the listing. A listing can be relisted after a
    failure and forfeit a second, entirely separate deposit; keying on the
    listing made the second forfeiture look like a replay of the first, so the
    ledger silently dropped it and a seller who failed twice paid once.

    One forfeiture per failed booking is the correct unit: it is the buyer
    being let down that triggers it.
    """
    return record(
        kind=KIND_FORFEIT, direction=DIRECTION_OUT, amount_paise=amount_paise,
        idempotency_key=f"forfeit:{booking_id}",
        listing_id=listing_id, booking_id=booking_id, user_id=seller_id,
        metadata={"reason": reason},
    )


def record_compensation(
    listing_id: str, booking_id: str, buyer_id: str, amount_paise: int, reason: str
):
    """Goodwill payment to the buyer, funded by the forfeited deposit."""
    return record(
        kind=KIND_COMPENSATION, direction=DIRECTION_OUT, amount_paise=amount_paise,
        idempotency_key=f"compensation:{booking_id}",
        listing_id=listing_id, booking_id=booking_id, user_id=buyer_id,
        metadata={"reason": reason},
    )


# ── Queries ───────────────────────────────────────────────────────────────────

def entries_for_listing(listing_id: str) -> list[dict]:
    r = (
        supabase.table("ledger_entries")
        .select("*")
        .eq("listing_id", listing_id)
        .order("created_at", desc=False)
        .execute()
    )
    return r.data or []


def settlement_balance_paise(booking_id: str, listing_id: str | None) -> int:
    """
    The real invariant: booking money and deposit money, together.

    `booking_balance_paise` alone reports a false negative on every forfeited
    booking. The deposit arrives tagged to the LISTING, while the compensation
    paid out of it is tagged to the BOOKING, so counting only booking-scoped
    rows sees the outflow and misses the inflow that funded it.

    Reconciliation checks this, plus each scope separately, so a genuine error
    in one cannot be hidden by an offsetting error in the other.
    """
    total = booking_balance_paise(booking_id)
    if not listing_id:
        return total

    # Only rows that are NOT already counted above, otherwise entries carrying
    # both ids (compensation, forfeit) would be double counted.
    for e in entries_for_listing(listing_id):
        if e.get("booking_id"):
            continue
        amount = int(e["amount_paise"])
        total += amount if e["direction"] == DIRECTION_IN else -amount
    return total


def deposit_balance_paise(listing_id: str) -> int:
    """
    Net of a listing's deposit entries. Zero once the deposit is resolved,
    either way. Non-zero on a settled listing means money is unaccounted for.
    """
    deposit_kinds = {
        KIND_DEPOSIT, KIND_DEPOSIT_RETURN, KIND_FORFEIT, KIND_COMPENSATION,
    }
    total = 0
    for e in entries_for_listing(listing_id):
        if e["kind"] not in deposit_kinds:
            continue
        amount = int(e["amount_paise"])
        total += amount if e["direction"] == DIRECTION_IN else -amount
    return total


def entries_for_booking(booking_id: str) -> list[dict]:
    r = (
        supabase.table("ledger_entries")
        .select("*")
        .eq("booking_id", booking_id)
        .order("created_at", desc=False)
        .execute()
    )
    return r.data or []


def booking_balance_paise(booking_id: str) -> int:
    """
    Sum of inflows minus outflows for a booking.

    Zero on a fully settled booking. Positive means the platform still holds
    money it owes someone; negative means it paid out more than it took.
    """
    total = 0
    for e in entries_for_booking(booking_id):
        amount = int(e["amount_paise"])
        total += amount if e["direction"] == DIRECTION_IN else -amount
    return total


def totals_by_kind(entries: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for e in entries:
        out[e["kind"]] = out.get(e["kind"], 0) + int(e["amount_paise"])
    return out
