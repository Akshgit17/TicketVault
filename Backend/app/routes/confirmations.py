from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timezone
from pydantic import BaseModel

from app.middleware.auth import get_current_user
from app.database import supabase
from app.services.stripe import refund_payment

router = APIRouter(prefix="/confirmations", tags=["confirmations"])
UTC = timezone.utc


def _get_user(clerk_id: str) -> dict:
    r = supabase.table("users").select("id").eq("clerk_id", clerk_id).single().execute()
    if not r.data:
        raise HTTPException(404, "User not found.")
    return r.data


def _get_paid_order(order_id: str, buyer_id: str) -> dict:
    r = (
        supabase.table("orders")
        .select("*, order_items(ticket_id, tickets(seller_id, price, listing_fee))")
        .eq("id", order_id)
        .eq("buyer_id", buyer_id)
        .single()
        .execute()
    )
    if not r.data:
        raise HTTPException(404, "Order not found.")
    order = r.data
    if order["payment_status"] != "paid":
        raise HTTPException(400, "Order has not been paid.")
    if order["confirmation_status"] not in ("pending",):
        raise HTTPException(400, f"Order already {order['confirmation_status']}.")
    return order


def _finalize_order(order: dict, status: str):
    supabase.table("orders").update({
        "confirmation_status": status,
    }).eq("id", order["id"]).execute()

    for item in order["order_items"]:
        ticket = item["tickets"]
        ticket_id = item["ticket_id"]

        supabase.table("tickets").update({
            "status": "sold",
        }).eq("id", ticket_id).execute()

        listing_fee_inr = float(ticket["listing_fee"])
        if listing_fee_inr > 0 and order.get("stripe_payment_intent"):
            try:
                refund_payment(
                    payment_intent_id=order["stripe_payment_intent"],
                    amount_paise=int(listing_fee_inr * 100),
                )
            except Exception:
                pass  # Reconcile manually


@router.post("/{order_id}/confirm")
async def confirm_order(
    order_id: str,
    claims: dict = Depends(get_current_user),
):
    buyer = _get_user(claims["sub"])
    order = _get_paid_order(order_id, buyer["id"])

    deadline = datetime.fromisoformat(order["confirmation_deadline"])
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    if datetime.now(UTC) > deadline:
        raise HTTPException(400, "Confirmation window has expired.")

    _finalize_order(order, "confirmed")
    return {"status": "confirmed", "order_id": order_id}


class DisputeRequest(BaseModel):
    reason: str


@router.post("/{order_id}/dispute")
async def dispute_order(
    order_id: str,
    body: DisputeRequest,
    claims: dict = Depends(get_current_user),
):
    buyer = _get_user(claims["sub"])
    order = _get_paid_order(order_id, buyer["id"])

    deadline = datetime.fromisoformat(order["confirmation_deadline"])
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    if datetime.now(UTC) > deadline:
        raise HTTPException(400, "Dispute window has expired.")

    supabase.table("orders").update({
        "confirmation_status": "disputed",
    }).eq("id", order["id"]).execute()

    return {"status": "disputed", "order_id": order_id, "reason": body.reason}
