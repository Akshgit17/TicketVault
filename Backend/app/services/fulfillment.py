"""
Fulfilment state machine.

The seller reassigns the ticket inside BookMyShow/District; the buyer confirms
it arrived in their account. Because the issuer transfer is single-use and
irreversible, the seller cannot retain a working copy — which the previous
QR-screenshot model could never guarantee.

TicketVault cannot perform the transfer (no public API). It orchestrates one:
notify, hold a deadline, collect proof, take the buyer's confirmation, then
release escrow.

Every transition goes through `transition()`, which validates against
ALLOWED and appends to booking_events. Nothing else may write
`fulfillment_status`.

ASSUMPTION — not yet validated (Phase 0.1):
    That BMS/District expose transfer for the events TicketVault lists, far
    enough ahead to be useful. Capability is therefore per-event *data*
    (`events.transfer_supported`, `transfer_window_opens_at`) rather than
    hardcoded. If validation shows transfer is sports-only or opens late, that
    is a data correction, not a rewrite.
"""
import logging
from datetime import datetime, timedelta, timezone

from app.config import FULFILLMENT_SLA_HOURS, SETTLEMENT_HOLD_HOURS
from app.database import supabase

logger = logging.getLogger(__name__)

UTC = timezone.utc

NOT_STARTED = "not_started"
AWAITING_TRANSFER = "awaiting_transfer"
TRANSFER_INITIATED = "transfer_initiated"
TRANSFER_CONFIRMED = "transfer_confirmed"
RELEASED = "released"
FAILED = "failed"

# The whole lifecycle, in one readable place.
ALLOWED: dict[str, set[str]] = {
    NOT_STARTED:        {AWAITING_TRANSFER, FAILED},
    AWAITING_TRANSFER:  {TRANSFER_INITIATED, FAILED},
    TRANSFER_INITIATED: {TRANSFER_CONFIRMED, FAILED},
    TRANSFER_CONFIRMED: {RELEASED, FAILED},
    RELEASED:           set(),      # terminal
    FAILED:             set(),      # terminal
}

TERMINAL = {RELEASED, FAILED}


class FulfillmentError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def transition(
    booking: dict,
    to_status: str,
    *,
    actor: str,
    actor_id: str | None = None,
    reason: str | None = None,
    extra_fields: dict | None = None,
    metadata: dict | None = None,
) -> dict:
    """
    Move a booking to `to_status`, or refuse.

    The update is guarded on the current status, so two concurrent callers
    cannot both transition the same booking — the loser gets a conflict rather
    than silently overwriting.
    """
    booking_id = booking["id"]
    from_status = booking.get("fulfillment_status", NOT_STARTED)

    if to_status not in ALLOWED.get(from_status, set()):
        raise FulfillmentError(
            "invalid_transition",
            f"Cannot move a booking from {from_status} to {to_status}.",
        )

    payload = {"fulfillment_status": to_status, **(extra_fields or {})}

    updated = (
        supabase.table("bookings")
        .update(payload)
        .eq("id", booking_id)
        .eq("fulfillment_status", from_status)   # CAS
        .execute()
    )

    if not updated.data:
        raise FulfillmentError(
            "conflict",
            "This booking was updated by someone else. Refresh and try again.",
        )

    _audit(booking_id, from_status, to_status, actor, actor_id, reason, metadata)
    logger.info(
        "Booking %s: %s -> %s (%s)", booking_id, from_status, to_status, actor,
        extra={"booking_id": booking_id, "from": from_status, "to": to_status},
    )
    return updated.data[0]


def _audit(booking_id, from_status, to_status, actor, actor_id, reason, metadata):
    try:
        supabase.table("booking_events").insert({
            "booking_id":  booking_id,
            "from_status": from_status,
            "to_status":   to_status,
            "actor":       actor,
            "actor_id":    actor_id,
            "reason":      reason,
            "metadata":    metadata or {},
        }).execute()
    except Exception:
        # The transition already happened; losing the audit row must not undo
        # it. Loud, because disputes are argued from this table.
        logger.exception(
            "AUDIT WRITE FAILED for booking %s (%s -> %s)",
            booking_id, from_status, to_status,
            extra={"booking_id": booking_id, "alert": True},
        )


# ── Entry point, called after payment settles ─────────────────────────────────

def begin_fulfillment(booking: dict, event: dict, buyer_mobile: str | None = None) -> dict:
    """
    Start the transfer clock for a freshly paid booking.

    Events not marked `transfer_supported` stay at not_started and fall back to
    the legacy QR flow — so enabling transfer is a per-event decision.
    """
    if not event.get("transfer_supported"):
        logger.info(
            "Booking %s: event %s is not transfer-enabled; using legacy flow",
            booking["id"], event.get("id"),
        )
        return booking

    now = datetime.now(UTC)

    # The transfer window may not be open yet — BMS enables transfer per event,
    # often close to the date. The SLA starts when the seller can actually act,
    # not when the buyer paid.
    window_opens = _parse_ts(event.get("transfer_window_opens_at"))
    starts_at = max(now, window_opens) if window_opens else now
    deadline = starts_at + timedelta(hours=FULFILLMENT_SLA_HOURS)

    # escrow_release_at is deliberately NOT set here. It is set when the buyer
    # confirms receipt — see confirm_transfer_received — because the clock runs
    # from confirmation, not from the event date.
    extra = {
        "transfer_deadline": deadline.isoformat(),
    }
    if buyer_mobile:
        extra["buyer_platform_mobile"] = buyer_mobile
        extra["mobile_consent_at"] = now.isoformat()

    return transition(
        booking, AWAITING_TRANSFER,
        actor="system", reason="payment settled", extra_fields=extra,
    )


# ── Seller and buyer actions ──────────────────────────────────────────────────

def mark_transfer_initiated(booking: dict, seller_id: str, proof_url: str | None = None) -> dict:
    """Seller states they have sent the ticket. Self-reported — not proof."""
    return transition(
        booking, TRANSFER_INITIATED,
        actor="seller", actor_id=seller_id, reason="seller marked transferred",
        extra_fields={
            "transfer_initiated_at": datetime.now(UTC).isoformat(),
            "transfer_proof_url": proof_url,
        },
    )


def confirm_transfer_received(booking: dict, buyer_id: str) -> dict:
    """
    Buyer confirms the ticket is in their own BMS/District account, which
    starts the payout clock.

    This is the real verification step. The old flow asked the buyer to confirm
    they could see a JPEG, which proved nothing.

    WHY THE CLOCK STARTS HERE, NOT AT THE EVENT
    -------------------------------------------
    Escrow used to release 24 hours after the event. That rule was written for
    the QR model, where a screenshot's validity is genuinely unknowable until
    someone is standing at the gate — so you had to wait for the gate.

    The transfer model earns an earlier release: the ticket is sitting in the
    buyer's own ticketing account, put there by the issuer, and the issuer has
    already validated what escrow was waiting to find out. Holding a seller's
    money for weeks past that point buys no additional safety.

    SETTLEMENT_HOLD_HOURS is the remaining margin — long enough for a buyer to
    notice a mis-transfer (wrong date, wrong seat, wrong event) and report it,
    short enough that an honest seller is not punished. Config-driven, so it
    can be set to seconds for a demo without editing code.
    """
    now = datetime.now(UTC)
    release_at = now + timedelta(hours=SETTLEMENT_HOLD_HOURS)

    return transition(
        booking, TRANSFER_CONFIRMED,
        actor="buyer", actor_id=buyer_id, reason="buyer confirmed receipt",
        extra_fields={
            "transfer_confirmed_at": now.isoformat(),
            "escrow_release_at":     release_at.isoformat(),
        },
    )


def fail_fulfillment(booking: dict, reason: str, actor: str = "system", actor_id: str | None = None) -> dict:
    return transition(
        booking, FAILED, actor=actor, actor_id=actor_id, reason=reason,
    )


def mark_released(booking: dict) -> dict:
    return transition(
        booking, RELEASED, actor="system", reason="escrow released after event",
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def can_dispute(booking: dict) -> bool:
    """
    Disputes stay open until escrow releases — i.e. past the event.

    The old design auto-confirmed 2 hours after purchase and then rejected any
    dispute, closing the window before the fraud was even discoverable.
    """
    return booking.get("fulfillment_status") not in TERMINAL
