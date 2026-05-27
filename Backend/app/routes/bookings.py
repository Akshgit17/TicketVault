from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel

from app.middleware.auth import get_current_user
from app.services.user_service import get_user_by_clerk_id
from app.database import supabase
from app.services.razorpay import create_order, verify_payment
from app.config import settings

router = APIRouter(prefix="/bookings", tags=["bookings"])
UTC = timezone.utc


def _extract_signed_url(result: object) -> str | None:
    """Handle supabase-py signed URL response shape differences."""
    if isinstance(result, dict):
        return result.get("signedURL") or result.get("signedUrl")
    return (
        getattr(result, "signedURL", None)
        or getattr(result, "signedUrl", None)
        or getattr(result, "signed_url", None)
    )




# ── SCHEMAS ───────────────────────────────────────────────────────────────────

class InitiateBookingRequest(BaseModel):
    listing_id:  str
    quantity:    int = 1
    buyer_name:  str
    buyer_email: str
    buyer_phone: str


class VerifyPaymentRequest(BaseModel):
    booking_id:           str
    razorpay_order_id:    str
    razorpay_payment_id:  str
    razorpay_signature:   str


class ConfirmBookingRequest(BaseModel):
    booking_id: str


class DisputeBookingRequest(BaseModel):
    booking_id: str
    reason:     str


# ── STEP 1 — Initiate booking + create Razorpay order ────────────────────────

@router.post("/initiate")
async def initiate_booking(
    body:   InitiateBookingRequest,
    claims: dict = Depends(get_current_user),
):
    buyer = get_user_by_clerk_id(claims["sub"])

    # Fetch listing
    r = (
        supabase.table("listings")
        .select("*, events(title)")
        .eq("id", body.listing_id)
        .execute()
    )
    if not r.data:
        raise HTTPException(404, "Listing not found.")

    listing = r.data[0]

    if listing["status"] != "active":
        raise HTTPException(409, "This listing is no longer available.")

    if listing["seller_id"] == buyer["id"]:
        raise HTTPException(400, "You cannot buy your own listing.")

    if body.quantity > listing["quantity"]:
        raise HTTPException(400, f"Only {listing['quantity']} ticket(s) available.")

    total = float(listing["price"]) * body.quantity

    # Lock listing atomically (only if still active)
    now         = datetime.now(UTC)
    lock_expiry = now + timedelta(minutes=5)

    lock_res = (
        supabase.table("listings")
        .update({
            "status":      "locked",
            "locked_by":   buyer["id"],
            "lock_expiry": lock_expiry.isoformat(),
        })
        .eq("id", body.listing_id)
        .eq("status", "active")          # atomic guard
        .execute()
    )

    if not lock_res.data:
        raise HTTPException(409, "Listing was just taken. Please try another.")

    # Create Razorpay order
    rz_order = create_order(
        amount_inr=total,
        receipt=f"tv_{body.listing_id[:8]}",
        notes={
            "listing_id": body.listing_id,
            "buyer_id":   buyer["id"],
        },
    )

    # Create booking record (pending)
    booking_res = supabase.table("bookings").insert({
        "user_id":          buyer["id"],
        "listing_id":       body.listing_id,
        "quantity":         body.quantity,
        "total_price":      total,
        "payment_status":   "pending",
        "razorpay_order_id": rz_order["id"],
        "buyer_name":       body.buyer_name,
        "buyer_email":      body.buyer_email,
        "buyer_phone":      body.buyer_phone,
    }).execute()

    booking = booking_res.data[0]

    return {
        "booking_id":        booking["id"],
        "razorpay_order_id": rz_order["id"],
        "razorpay_key_id":   settings.RAZORPAY_KEY_ID,
        "amount":            total,
        "currency":          "INR",
        "lock_expiry":       lock_expiry.isoformat(),
    }


# ── STEP 2 — Verify Razorpay payment ─────────────────────────────────────────

@router.post("/verify-payment")
async def verify_booking_payment(
    body:   VerifyPaymentRequest,
    claims: dict = Depends(get_current_user),
):
    buyer = get_user_by_clerk_id(claims["sub"])

    # Fetch booking
    r = (
        supabase.table("bookings")
        .select("*, listings(id, seller_id, price, listing_fee, quantity)")
        .eq("id", body.booking_id)
        .eq("user_id", buyer["id"])
        .execute()
    )
    if not r.data:
        raise HTTPException(404, "Booking not found.")

    booking = r.data[0]

    if booking["payment_status"] == "paid":
        return {"status": "already_paid", "booking_id": body.booking_id}

    # Verify signature
    is_valid = verify_payment(
        razorpay_order_id=body.razorpay_order_id,
        razorpay_payment_id=body.razorpay_payment_id,
        razorpay_signature=body.razorpay_signature,
    )

    if not is_valid:
        # Release listing lock on failure
        supabase.table("listings").update({
            "status":      "active",
            "locked_by":   None,
            "lock_expiry": None,
        }).eq("id", booking["listing_id"]).execute()

        supabase.table("bookings").update({
            "payment_status": "failed",
        }).eq("id", body.booking_id).execute()

        raise HTTPException(400, "Payment verification failed. Invalid signature.")

    # Payment valid — finalize
    now      = datetime.now(UTC)
    deadline = now + timedelta(hours=2)

    supabase.table("bookings").update({
        "payment_status":        "paid",
        "razorpay_payment_id":   body.razorpay_payment_id,
        "confirmation_status":   "pending",
        "confirmation_deadline": deadline.isoformat(),
    }).eq("id", body.booking_id).execute()

    # Mark listing sold
    supabase.table("listings").update({
        "status":      "sold",
        "locked_by":   None,
        "lock_expiry": None,
    }).eq("id", booking["listing_id"]).execute()

    return {
        "status":                "paid",
        "booking_id":            body.booking_id,
        "confirmation_deadline": deadline.isoformat(),
    }


# ── GET my bookings ───────────────────────────────────────────────────────────

@router.get("/my/all")
async def my_bookings(claims: dict = Depends(get_current_user)):
    buyer = get_user_by_clerk_id(claims["sub"])

    r = (
        supabase.table("bookings")
        .select("""
            *,
            listings(
                id, price, quantity,
                events(title, date, venue, image_url),
                cities(name)
            )
        """)
        .eq("user_id", buyer["id"])
        .order("created_at", desc=True)
        .execute()
    )
    return r.data or []


# ── GET booking details ───────────────────────────────────────────────────────

@router.get("/{booking_id}")
async def get_booking(
    booking_id: str,
    claims:     dict = Depends(get_current_user),
):
    buyer = get_user_by_clerk_id(claims["sub"])

    r = (
        supabase.table("bookings")
        .select("""
            *,
            listings(
                id, price, original_price, quantity, qr_image_url,
                events(title, date, venue, image_url),
                cities(name)
            )
        """)
        .eq("id", booking_id)
        .eq("user_id", buyer["id"])
        .execute()
    )

    if not r.data:
        raise HTTPException(404, "Booking not found.")

    booking = r.data[0]

    # Attach QR URL if paid.
    # Some historical rows may store a full public URL instead of storage path.
    if booking["payment_status"] == "paid":
        listing = booking.get("listings") or {}
        qr_path = listing.get("qr_image_url")
        if qr_path:
            try:
                if isinstance(qr_path, str) and qr_path.startswith(("http://", "https://")):
                    booking["qr_signed_url"] = qr_path
                else:
                    signed = supabase.storage.from_("ticket-qrs").create_signed_url(
                        qr_path, expires_in=3600
                    )
                    booking["qr_signed_url"] = _extract_signed_url(signed)
                    if not booking["qr_signed_url"]:
                        # Last-resort fallback when signer response shape changes.
                        booking["qr_signed_url"] = (
                            f"{settings.SUPABASE_URL}/storage/v1/object/public/ticket-qrs/{qr_path}"
                        )
            except Exception:
                booking["qr_signed_url"] = None

    return booking


# ── CONFIRM / DISPUTE ─────────────────────────────────────────────────────────

@router.post("/confirm")
async def confirm_booking(
    body:   ConfirmBookingRequest,
    claims: dict = Depends(get_current_user),
):
    buyer = get_user_by_clerk_id(claims["sub"])
    r = (
        supabase.table("bookings")
        .select("*")
        .eq("id", body.booking_id)
        .eq("user_id", buyer["id"])
        .execute()
    )
    if not r.data:
        raise HTTPException(404, "Booking not found.")
    booking = r.data[0]

    if booking["payment_status"] != "paid":
        raise HTTPException(400, "Booking not paid.")
    if booking["confirmation_status"] != "pending":
        raise HTTPException(400, f"Already {booking['confirmation_status']}.")

    deadline = datetime.fromisoformat(booking["confirmation_deadline"])
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    if datetime.now(UTC) > deadline:
        raise HTTPException(400, "Confirmation window expired.")

    supabase.table("bookings").update({
        "confirmation_status": "confirmed",
    }).eq("id", body.booking_id).execute()

    return {"status": "confirmed", "booking_id": body.booking_id}


@router.post("/dispute")
async def dispute_booking(
    body:   DisputeBookingRequest,
    claims: dict = Depends(get_current_user),
):
    buyer = get_user_by_clerk_id(claims["sub"])
    r = (
        supabase.table("bookings")
        .select("*")
        .eq("id", body.booking_id)
        .eq("user_id", buyer["id"])
        .execute()
    )
    if not r.data:
        raise HTTPException(404, "Booking not found.")
    booking = r.data[0]

    if booking["payment_status"] != "paid":
        raise HTTPException(400, "Booking not paid.")
    if booking["confirmation_status"] != "pending":
        raise HTTPException(400, f"Already {booking['confirmation_status']}.")

    supabase.table("bookings").update({
        "confirmation_status": "disputed",
    }).eq("id", body.booking_id).execute()

    return {"status": "disputed", "booking_id": body.booking_id}
