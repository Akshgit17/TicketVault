from fastapi import APIRouter, Depends, HTTPException, Request
from datetime import datetime, timedelta, timezone
import stripe

from app.middleware.auth import get_current_user
from app.database import supabase
from app.services.stripe import create_payment_intent, refund_payment
from app.schemas.orders import InitiateBuyRequest
from app.config import settings

router = APIRouter(prefix="/orders", tags=["orders"])
UTC = timezone.utc


def _get_user(clerk_id: str) -> dict:
    r = supabase.table("users").select("id").eq("clerk_id", clerk_id).single().execute()
    if not r.data:
        raise HTTPException(404, "User not found.")
    return r.data


def _release_lock(ticket_id: str):
    supabase.table("tickets").update({
        "status": "available",
        "locked_by": None,
        "lock_expiry": None,
    }).eq("id", ticket_id).execute()


@router.post("/initiate")
async def initiate_buy(
    body: InitiateBuyRequest,
    claims: dict = Depends(get_current_user),
):
    buyer = _get_user(claims["sub"])
    ticket_id = str(body.ticket_id)

    r = (
        supabase.table("tickets")
        .select("*, events(name)")
        .eq("id", ticket_id)
        .single()
        .execute()
    )
    ticket = r.data
    if not ticket:
        raise HTTPException(404, "Ticket not found.")

    if ticket["status"] != "available":
        raise HTTPException(409, "Ticket is no longer available.")

    if ticket["seller_id"] == buyer["id"]:
        raise HTTPException(400, "You cannot buy your own ticket.")

    now = datetime.now(UTC)
    lock_expiry = now + timedelta(minutes=10)

    lock_res = (
        supabase.table("tickets")
        .update({
            "status": "locked",
            "locked_by": buyer["id"],
            "lock_expiry": lock_expiry.isoformat(),
        })
        .eq("id", ticket_id)
        .eq("status", "available")
        .execute()
    )

    if not lock_res.data:
        raise HTTPException(409, "Ticket was just taken. Please try another.")

    intent = create_payment_intent(
        amount_inr=float(ticket["price"]),
        metadata={"ticket_id": ticket_id, "buyer_id": buyer["id"]},
    )

    order_res = (
        supabase.table("orders")
        .insert({
            "buyer_id": buyer["id"],
            "total_price": float(ticket["price"]),
            "payment_status": "pending",
            "stripe_payment_intent": intent["payment_intent_id"],
            "confirmation_status": "pending",
        })
        .execute()
    )
    order = order_res.data[0]

    supabase.table("order_items").insert({
        "order_id": order["id"],
        "ticket_id": ticket_id,
    }).execute()

    return {
        "order_id": order["id"],
        "client_secret": intent["client_secret"],
        "lock_expiry": lock_expiry.isoformat(),
        "amount": float(ticket["price"]),
    }


@router.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except stripe.error.SignatureVerificationError:
        raise HTTPException(400, "Invalid webhook signature.")

    if event["type"] == "payment_intent.succeeded":
        await _handle_payment_success(event["data"]["object"])
    elif event["type"] == "payment_intent.payment_failed":
        await _handle_payment_failure(event["data"]["object"])

    return {"received": True}


async def _handle_payment_success(intent: dict):
    pi_id = intent["id"]
    ticket_id = intent["metadata"].get("ticket_id")
    if not ticket_id:
        return
    now = datetime.now(UTC)
    deadline = now + timedelta(hours=2)
    supabase.table("orders").update({
        "payment_status": "paid",
        "confirmation_deadline": deadline.isoformat(),
    }).eq("stripe_payment_intent", pi_id).execute()
    supabase.table("tickets").update({
        "status": "pending_confirmation",
        "locked_by": None,
        "lock_expiry": None,
    }).eq("id", ticket_id).execute()


async def _handle_payment_failure(intent: dict):
    pi_id = intent["id"]
    ticket_id = intent["metadata"].get("ticket_id")
    if not ticket_id:
        return
    _release_lock(ticket_id)
    supabase.table("orders").update({
        "payment_status": "failed",
    }).eq("stripe_payment_intent", pi_id).execute()


@router.get("/{order_id}")
async def get_order(
    order_id: str,
    claims: dict = Depends(get_current_user),
):
    buyer = _get_user(claims["sub"])
    r = (
        supabase.table("orders")
        .select("""
            *,
            order_items(
                ticket_id,
                tickets(
                    price, original_price, status, listing_fee,
                    events(name, date, venue),
                    cities(name)
                )
            )
        """)
        .eq("id", order_id)
        .eq("buyer_id", buyer["id"])
        .single()
        .execute()
    )
    if not r.data:
        raise HTTPException(404, "Order not found.")

    order = r.data

    if order["payment_status"] == "paid":
        for item in order["order_items"]:
            qr = (
                supabase.table("ticket_qrs")
                .select("qr_image_url")
                .eq("ticket_id", item["ticket_id"])
                .execute()
            )
            if qr.data:
                path = qr.data[0]["qr_image_url"]
                signed = supabase.storage.from_("ticket-qrs").create_signed_url(
                    path, expires_in=3600
                )
                item["qr_signed_url"] = signed.get("signedURL")

    return order
