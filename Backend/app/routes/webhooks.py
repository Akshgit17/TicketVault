"""
Razorpay webhooks — the authoritative record of what was paid.

The client calling /bookings/verify-payment is advisory: it may advance the UI
optimistically, but a buyer who closes the tab mid-payment never sends it. The
webhook always arrives, so settlement must not depend on the browser.

Ordering is not guaranteed — the webhook may arrive before or after the client
call. Both paths route through app.services.settlement, which is idempotent.

HTTP contract with Razorpay:
  200  handled, or deliberately ignored — stop retrying
  4xx  bad signature / malformed — stop retrying, this will never succeed
  5xx  transient failure on our side — please retry
"""
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from app.config import settings
from app.database import supabase
from app.services.payments import to_paise
from app.services.razorpay import client
from app.services.settlement import (
    SettlementError,
    activate_listing_after_fee,
    fail_booking,
    settle_booking,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])

HANDLED_EVENTS = {"payment.captured", "order.paid", "payment.failed"}


def _verify_signature(raw_body: bytes, signature: str) -> bool:
    try:
        client.utility.verify_webhook_signature(
            raw_body.decode("utf-8"),
            signature,
            settings.RAZORPAY_WEBHOOK_SECRET,
        )
        return True
    except Exception as e:
        logger.warning("Webhook signature verification failed: %s", e)
        return False


def _already_processed(event_id: str) -> bool:
    r = (
        supabase.table("webhook_events")
        .select("id")
        .eq("provider", "razorpay")
        .eq("event_id", event_id)
        .execute()
    )
    return bool(r.data)


def _record_event(event_id: str, event_type: str, payload: dict, status: str, error: str | None = None):
    try:
        supabase.table("webhook_events").insert({
            "provider":   "razorpay",
            "event_id":   event_id,
            "event_type": event_type,
            "payload":    payload,
            "status":     status,
            "error":      error,
        }).execute()
    except Exception as e:
        # A duplicate here means a concurrent delivery of the same event won the
        # race. That is fine — the handlers are idempotent.
        logger.info("Could not record webhook event %s: %s", event_id, e)


@router.post("/razorpay")
async def razorpay_webhook(request: Request):
    raw = await request.body()
    signature = request.headers.get("x-razorpay-signature", "")

    if not signature or not _verify_signature(raw, signature):
        raise HTTPException(400, "Invalid webhook signature.")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(400, "Malformed webhook body.")

    event_type = payload.get("event", "")
    # Razorpay sends x-razorpay-event-id; fall back to the payment id so we
    # still deduplicate if the header is absent.
    event_id = request.headers.get("x-razorpay-event-id") or _fallback_event_id(payload)

    if not event_id:
        logger.warning("Webhook without an identifiable event id: %s", event_type)
        return {"status": "ignored", "reason": "no_event_id"}

    # Everything below is blocking Supabase I/O. This handler must stay async
    # for `request.body()`, so the blocking half runs in the threadpool.
    return await run_in_threadpool(_process, event_id, event_type, payload)


def _process(event_id: str, event_type: str, payload: dict) -> dict:
    if _already_processed(event_id):
        return {"status": "duplicate", "event_id": event_id}

    if event_type not in HANDLED_EVENTS:
        _record_event(event_id, event_type, payload, "ignored")
        return {"status": "ignored", "event": event_type}

    try:
        result = _handle(event_type, payload)
    except SettlementError as e:
        _record_event(event_id, event_type, payload, "failed", e.message)
        # Not retryable — the state is wrong, not transient.
        logger.error("Webhook %s settlement rejected: %s", event_id, e.message)
        return {"status": "rejected", "reason": e.code}
    except Exception as e:
        _record_event(event_id, event_type, payload, "failed", str(e))
        logger.exception("Webhook %s failed", event_id)
        # 500 so Razorpay retries.
        raise HTTPException(500, "Webhook processing failed.")

    _record_event(event_id, event_type, payload, "processed")
    return {"status": "processed", "event": event_type, "result": result}


def _fallback_event_id(payload: dict) -> str | None:
    entity = _payment_entity(payload) or {}
    pid = entity.get("id")
    return f"{payload.get('event')}:{pid}" if pid else None


def _payment_entity(payload: dict) -> dict | None:
    return (payload.get("payload", {}).get("payment", {}) or {}).get("entity")


def _order_entity(payload: dict) -> dict | None:
    return (payload.get("payload", {}).get("order", {}) or {}).get("entity")


def _handle(event_type: str, payload: dict) -> dict:
    entity = _payment_entity(payload) or _order_entity(payload)
    if not entity:
        return {"status": "ignored", "reason": "no_entity"}

    order_id = entity.get("order_id") or entity.get("id")
    payment_id = entity.get("id") if entity.get("order_id") else None
    amount = entity.get("amount")

    if not order_id:
        return {"status": "ignored", "reason": "no_order_id"}

    # Is this a booking payment?
    br = supabase.table("bookings").select("*").eq("razorpay_order_id", order_id).execute()
    if br.data:
        booking = br.data[0]

        if event_type == "payment.failed":
            fail_booking(booking, "payment.failed", "webhook")
            return {"status": "failed", "booking_id": booking["id"]}

        expected = to_paise(booking["total_price"])
        if amount is not None and int(amount) != expected:
            # Never settle a booking for the wrong amount, even from a signed
            # webhook. Record it and leave the booking pending for review.
            raise SettlementError(
                "amount_mismatch",
                f"Webhook amount {amount} != expected {expected} for booking {booking['id']}",
            )

        if not payment_id:
            return {"status": "ignored", "reason": "no_payment_id"}

        return settle_booking(booking, payment_id, "webhook")

    # Is this a listing fee payment?
    lr = supabase.table("listings").select("*").eq("fee_razorpay_order_id", order_id).execute()
    if lr.data:
        listing = lr.data[0]
        if event_type == "payment.failed":
            return {"status": "ignored", "reason": "fee_payment_failed"}
        if not payment_id:
            return {"status": "ignored", "reason": "no_payment_id"}
        return activate_listing_after_fee(listing, payment_id, "webhook")

    # Unknown order — a test event, or an order from another environment sharing
    # the same Razorpay account. Acknowledge so Razorpay stops retrying.
    logger.info("Webhook for unknown order %s", order_id)
    return {"status": "ignored", "reason": "unknown_order"}
