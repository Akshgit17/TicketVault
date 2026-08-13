"""
Seller payout onboarding endpoints.

The submitted account number and PAN are never persisted in full and never
logged — see app/services/seller_accounts.py for the storage contract.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.database import supabase
from app.middleware.auth import get_current_user
from app.services.seller_accounts import (
    SellerAccountError,
    configure_payout_account,
    payout_status,
)
from app.services.user_service import get_user_by_clerk_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sellers", tags=["sellers"])


class PayoutAccountRequest(BaseModel):
    account_number:   str = Field(min_length=9,  max_length=18)
    ifsc:             str = Field(min_length=11, max_length=11)
    beneficiary_name: str = Field(min_length=3,  max_length=120)
    pan:              str = Field(min_length=10, max_length=10)

    # Keep these out of validation-error output, which FastAPI echoes back and
    # which gets logged upstream.
    model_config = {"json_schema_extra": {"example": {
        "account_number": "000123456789",
        "ifsc": "HDFC0001234",
        "beneficiary_name": "A Sharma",
        "pan": "ABCDE1234F",
    }}}


@router.get("/me/payout")
def get_payout_account(claims: dict = Depends(get_current_user)):
    """Masked view of the caller's payout setup."""
    user = get_user_by_clerk_id(claims["sub"])
    return payout_status(user)


@router.post("/me/payout")
def set_payout_account(
    body:   PayoutAccountRequest,
    claims: dict = Depends(get_current_user),
):
    user = get_user_by_clerk_id(claims["sub"])
    try:
        result = configure_payout_account(
            user,
            account_number=body.account_number,
            ifsc=body.ifsc,
            beneficiary_name=body.beneficiary_name,
            pan=body.pan,
        )
    except SellerAccountError as e:
        # 422 for input the seller can fix, 502 when the provider failed.
        status = 502 if e.code == "provider_failed" else 422
        raise HTTPException(status, e.message)

    refreshed = get_user_by_clerk_id(claims["sub"])
    return {**result, **payout_status(refreshed)}


@router.get("/me/sales")
def get_sales(claims: dict = Depends(get_current_user)):
    """
    Bookings placed against the caller's listings — the seller's side of a sale.

    This did not exist before, which is why nothing could call
    POST /bookings/mark-transferred: a seller had no way to learn that their
    ticket had sold, let alone act on it. /bookings/my/all filters on
    `user_id`, which is the *buyer*.

    The buyer's platform mobile is included only once they have consented to
    share it, because the transfer cannot be performed without it.
    """
    seller = get_user_by_clerk_id(claims["sub"])

    listings = (
        supabase.table("listings")
        .select("id")
        .eq("seller_id", seller["id"])
        .execute()
    ).data or []

    if not listings:
        return []

    rows = (
        supabase.table("bookings")
        .select(
            "*, listings(id, price, original_price, seller_id,"
            " events(id, title, date, venue, image_url), cities(name))"
        )
        .in_("listing_id", [l["id"] for l in listings])
        .eq("payment_status", "paid")
        .order("created_at", desc=True)
        .execute()
    ).data or []

    for booking in rows:
        # Never expose the buyer's contact detail until consent is recorded.
        if not booking.get("mobile_consent_at"):
            booking["buyer_platform_mobile"] = None

    return rows


@router.get("/me/earnings")
def get_earnings(claims: dict = Depends(get_current_user)):
    """What the seller has been paid, and what is still owed to them."""
    user = get_user_by_clerk_id(claims["sub"])

    rows = (
        supabase.table("payouts")
        .select("*")
        .eq("seller_id", user["id"])
        .order("created_at", desc=True)
        .execute()
    ).data or []

    paid = [p for p in rows if p["status"] == "paid"]
    pending = [p for p in rows if p["status"] in ("pending", "processing")]

    return {
        "total_paid_paise":    sum(int(p["net_paise"]) for p in paid),
        "total_pending_paise": sum(int(p["net_paise"]) for p in pending),
        "payouts": [
            {
                "booking_id":  p["booking_id"],
                "net_paise":   int(p["net_paise"]),
                "fee_paise":   int(p["fee_paise"]),
                "status":      p["status"],
                "paid_at":     p.get("paid_at"),
                # A `sim_` transfer id means no money actually left the
                # platform account. Surfaced rather than hidden: a payout page
                # that says "paid" about money that never moved is the kind of
                # thing that looks like concealment when someone finds it, and
                # like engineering judgement when you point at it first.
                "simulated":   str(p.get("razorpay_transfer_id") or "").startswith("sim_"),
                "transfer_id": p.get("razorpay_transfer_id"),
            }
            for p in rows
        ],
    }
