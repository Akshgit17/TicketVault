import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.concurrency import run_in_threadpool
from decimal import Decimal
from pydantic import BaseModel, Field
from postgrest.exceptions import APIError

from app.middleware.auth import get_current_user
from app.services.user_service import get_user_by_clerk_id
from app.database import supabase
from app.services import deposits
from app.services.qr import decode_qr, generate_fingerprint
from app.services.storage import upload_qr_image

from app.services.razorpay import create_order
from app.services.payments import (
    PaymentVerificationError,
    to_paise,
    verify_payment_for,
)
from app.services.seller_accounts import can_sell
from app.services.settlement import activate_listing_after_fee
from app.config import (
    settings,
    BUYER_COMPENSATION_RATE,
    LISTING_FEE_RATE,
    PRICE_CAP_MULTIPLIER,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/listings", tags=["listings"])


def _validate_city(city_id: str):
    r = supabase.table("cities").select("id").eq("id", city_id).eq("is_active", True).execute()
    if not r.data:
        raise HTTPException(400, "Invalid or inactive city.")


def _validate_event_city(event_id: str, city_id: str):
    """
    The event exists, matches the chosen city, and can still be fulfilled.

    Filtering past and cancelled events out of the browse endpoints is not the
    same as preventing them. A stale tab, a bookmark, or a link shared an hour
    ago all reach this endpoint directly, so the rule has to live where the row
    is written rather than only where rows are read.
    """
    r = (
        supabase.table("events")
        .select("city_id, date, cancelled_at, title")
        .eq("id", event_id)
        .execute()
    )
    if not r.data:
        raise HTTPException(404, "Event not found.")

    event = r.data[0]
    if event["city_id"] != city_id:
        raise HTTPException(400, "Event city does not match selected city.")

    if event.get("cancelled_at"):
        raise HTTPException(400, "That concert has been cancelled.")

    event_date = _parse_ts(event.get("date"))
    if event_date and event_date <= datetime.now(timezone.utc):
        # Nothing can be transferred to a show that already started, so a
        # listing here could only ever end in a refund.
        raise HTTPException(400, "That concert has already started.")


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# ── GET listings (public — no auth) ──────────────────────────────────────────

@router.get("")
def list_listings(
    city_id:      str | None = None,
    event_id:     str | None = None,
    include_past: bool = False,
):
    q = (
        supabase.table("listings")
        .select("""
            *,
            events!inner(id, title, date, venue, image_url),
            cities(name)
        """)
        .eq("status", "active")
    )
    if city_id:
        q = q.eq("city_id", city_id)
    if event_id:
        q = q.eq("event_id", event_id)

    # Listings for concerts that have already happened are unsellable and
    # unfulfillable — the seller cannot transfer a ticket to a past show.
    # /events already excluded past events; without the same filter here the
    # marketplace kept offering them. `!inner` on the join is required for the
    # nested filter to apply.
    # Same reasoning as /events: nobody may buy a ticket to a cancelled show.
    # The cancel path withdraws these listings anyway, so this is the backstop
    # for a cancellation that failed part way through.
    q = q.is_("events.cancelled_at", "null")

    if not include_past:
        q = q.gte("events.date", datetime.now(timezone.utc).isoformat())

    try:
        r = q.order("created_at", desc=True).execute()
        return r.data or []
    except APIError as e:
        # During partial migrations, listings table can be absent.
        if "public.listings" in str(e):
            return []
        raise


# ── FEE PAYMENT ──────────────────────────────────────────────────────────────

class VerifyFeeRequest(BaseModel):
    razorpay_order_id:   str
    razorpay_payment_id: str
    razorpay_signature:  str

@router.post("/{listing_id}/initiate-fee")
def initiate_listing_fee(
    listing_id: str,
    claims:     dict = Depends(get_current_user),
):
    seller = get_user_by_clerk_id(claims["sub"])
    r = supabase.table("listings").select("*").eq("id", listing_id).eq("seller_id", seller["id"]).execute()
    if not r.data:
        raise HTTPException(404, "Listing not found.")
    
    listing = r.data[0]
    if listing["status"] != "pending_fee":
        raise HTTPException(400, f"Listing status is {listing['status']}, cannot pay fee.")

    fee_amount = float(listing["price"]) * LISTING_FEE_RATE

    # Create Razorpay order for the fee
    try:
        rz_order = create_order(
            amount_inr=fee_amount,
            receipt=f"fee_{listing_id[:8]}",
            notes={"listing_id": listing_id, "type": "listing_fee"}
        )
        
        # Save order ID to listing
        supabase.table("listings").update({
            "fee_razorpay_order_id": rz_order["id"]
        }).eq("id", listing_id).execute()
        
        return {
            "razorpay_order_id": rz_order["id"],
            "razorpay_key_id":   settings.RAZORPAY_KEY_ID,
            "amount":            fee_amount,
        }
    except Exception:
        logger.exception("Razorpay order creation failed for listing %s", listing_id)
        raise HTTPException(502, "Could not reach the payment provider. Please retry.")

@router.post("/{listing_id}/verify-fee")
def verify_listing_fee(
    listing_id: str,
    body:       VerifyFeeRequest,
    claims:     dict = Depends(get_current_user),
):
    seller = get_user_by_clerk_id(claims["sub"])

    # Load the listing first — we need its own order id to bind against.
    lr = (
        supabase.table("listings")
        .select("*")
        .eq("id", listing_id)
        .eq("seller_id", seller["id"])
        .execute()
    )
    if not lr.data:
        raise HTTPException(404, "Listing not found or not yours.")

    listing = lr.data[0]
    if listing["status"] != "pending_fee":
        raise HTTPException(400, f"Listing status is {listing['status']}, fee not payable.")

    try:
        verify_payment_for(
            expected_order_id=listing.get("fee_razorpay_order_id"),
            expected_amount_paise=to_paise(float(listing["price"]) * LISTING_FEE_RATE),
            razorpay_order_id=body.razorpay_order_id,
            razorpay_payment_id=body.razorpay_payment_id,
            razorpay_signature=body.razorpay_signature,
        )
    except PaymentVerificationError as e:
        raise HTTPException(400, e.message)

    # Shared with the webhook path; guarded on pending_fee so a paid receipt can
    # never reactivate a sold listing.
    return activate_listing_after_fee(listing, body.razorpay_payment_id, "client")


# ── GET my listings (auth required) ──────────────────────────────────────────

@router.get("/my/all")
def my_listings(claims: dict = Depends(get_current_user)):
    seller = get_user_by_clerk_id(claims["sub"])
    r = (
        supabase.table("listings")
        .select("*, events(id, title, date, venue), cities(name)")
        .eq("seller_id", seller["id"])
        .order("created_at", desc=True)
        .execute()
    )
    return r.data or []


# ── GET single listing ────────────────────────────────────────────────────────

@router.get("/{listing_id}")
def get_listing(listing_id: str):
    r = (
        supabase.table("listings")
        .select("""
            *,
            events(id, title, date, venue, image_url),
            cities(name)
        """)
        .eq("id", listing_id)
        .execute()
    )
    if not r.data:
        raise HTTPException(404, "Listing not found.")
    return r.data[0]


# ── CREATE listing (auth required) ────────────────────────────────────────────

MAX_QR_UPLOAD_BYTES = 5 * 1024 * 1024   # 5 MB
_UPLOAD_CHUNK = 64 * 1024


async def _read_upload_limited(upload: UploadFile) -> bytes:
    """
    Read an upload, refusing anything over the limit.

    Reads in chunks and stops at the threshold rather than trusting
    Content-Length, so an oversized body cannot be buffered into memory and
    then handed to OpenCV.
    """
    buf = bytearray()
    while chunk := await upload.read(_UPLOAD_CHUNK):
        buf.extend(chunk)
        if len(buf) > MAX_QR_UPLOAD_BYTES:
            raise HTTPException(
                413,
                f"QR image too large (limit {MAX_QR_UPLOAD_BYTES // (1024 * 1024)} MB).",
            )
    if not buf:
        raise HTTPException(422, "Empty file uploaded.")
    return bytes(buf)


def _persist_listing(
    *,
    image_bytes: bytes,
    content_type: str,
    event_id: str,
    city_id: str,
    seller_id: str,
    price: float,
    original_price: float,
    quantity: int,
) -> dict:
    """Blocking half of create_listing — decode, dedupe, upload, insert."""
    try:
        qr_data = decode_qr(image_bytes)
    except Exception as e:
        raise HTTPException(422, str(e))

    qr_fingerprint = generate_fingerprint(qr_data)

    # Duplicate check (ignore cancelled listings)
    dup = (
        supabase.table("listings")
        .select("id")
        .eq("qr_fingerprint", qr_fingerprint)
        .neq("status", "cancelled")
        .execute()
    )
    if dup.data:
        raise HTTPException(409, "Duplicate QR detected. This ticket is already actively listed or sold.")

    qr_url = upload_qr_image(image_bytes, content_type)

    listing_res = supabase.table("listings").insert({
        "event_id":       event_id,
        "seller_id":      seller_id,
        "city_id":        city_id,
        "price":          price,
        "original_price": original_price,
        "quantity":       quantity,
        "status":         "pending_fee",
        "qr_image_url":   qr_url,
        "qr_fingerprint": qr_fingerprint,
    }).execute()

    return listing_res.data[0]

@router.post("/create")
async def create_listing(
    event_id:       str     = Form(...),
    city_id:        str     = Form(...),
    price:          str     = Form(...),
    original_price: str     = Form(...),
    quantity:       str     = Form("1"),
    qr_file:        UploadFile = File(...),
    claims:         dict    = Depends(get_current_user),
):
    logger.info("create_listing: event_id=%s city_id=%s", event_id, city_id)

    # Cast manually to avoid 422s from Pydantic before we can log
    try:
        d_price = Decimal(price)
        d_orig  = Decimal(original_price)
        i_qty   = int(quantity)
    except Exception as e:
        raise HTTPException(422, f"Invalid numeric value: {e}")

    seller = get_user_by_clerk_id(claims["sub"])

    # A seller who cannot be paid should not be able to take a buyer's money.
    # No-op until REQUIRE_PAYOUT_ACCOUNT is enabled (see app/config.py).
    allowed, reason = can_sell(seller)
    if not allowed:
        raise HTTPException(403, reason)

    _validate_city(city_id)
    _validate_event_city(event_id, city_id)

    # Calculate fee for metadata
    fee_amount = float(d_price) * LISTING_FEE_RATE

    if d_price <= 0 or d_orig <= 0:
        raise HTTPException(400, "Prices must be positive.")
    if i_qty < 1:
        raise HTTPException(400, "Quantity must be at least 1.")

    image_bytes = await _read_upload_limited(qr_file)

    # QR decoding is OpenCV — CPU-bound — and the storage upload and inserts are
    # blocking network calls. This handler must stay async for `qr_file.read()`,
    # so the rest is pushed to the threadpool explicitly.
    listing = await run_in_threadpool(
        _persist_listing,
        image_bytes=image_bytes,
        content_type=qr_file.content_type or "image/png",
        event_id=event_id,
        city_id=city_id,
        seller_id=seller["id"],
        price=float(d_price),
        original_price=float(d_orig),
        quantity=i_qty,
    )
    return {
        "listing_id":  listing["id"],
        "status":      "pending_fee",
        "listing_fee": fee_amount,
    }


# ── UNLIST ───────────────────────────────────────────────────────────────────

class UpdatePriceRequest(BaseModel):
    price: Decimal = Field(gt=0)


@router.post("/{listing_id}/price")
def update_listing_price(
    listing_id: str,
    body:   UpdatePriceRequest,
    claims: dict = Depends(get_current_user),
):
    """
    Reprice a live listing without unlisting it.

    Without this a seller who priced badly had only one option: unlist and
    start again, which meant paying a second deposit to fix a typo.

    The deposit is NOT recalculated. It was taken as a percentage of the
    original asking price and is returned in full on a completed sale, so an
    over- or under-collateralised listing costs the seller nothing either way.
    What does matter is the failure case: a forfeited deposit has to be large
    enough to pay the buyer's compensation, which is a percentage of the price
    they actually paid. So the only price rise refused is one the existing
    deposit could no longer cover.
    """
    seller = get_user_by_clerk_id(claims["sub"])

    r = (
        supabase.table("listings")
        .select("*")
        .eq("id", listing_id)
        .eq("seller_id", seller["id"])
        .execute()
    )
    if not r.data:
        raise HTTPException(404, "Listing not found.")
    listing = r.data[0]

    if listing["status"] != "active":
        raise HTTPException(
            409,
            "Only a live listing can be repriced. This one is "
            f"{listing['status'].replace('_', ' ')}.",
        )

    new_price = body.price
    original = Decimal(str(listing["original_price"]))
    cap = original * Decimal(str(PRICE_CAP_MULTIPLIER))

    if new_price > cap:
        raise HTTPException(
            400,
            f"Capped at {cap:.0f}, which is "
            f"{int(PRICE_CAP_MULTIPLIER * 100)}% of the face value.",
        )

    # The deposit already taken must still cover what the buyer would be owed
    # if this sale failed. Deposit is LISTING_FEE_RATE of the old price and
    # compensation is BUYER_COMPENSATION_RATE of the new one, so in practice
    # this allows roughly a doubling before it bites.
    deposit_paise = listing.get("deposit_paid_paise")
    if deposit_paise:
        max_covered = Decimal(int(deposit_paise)) / Decimal(100) / Decimal(
            str(BUYER_COMPENSATION_RATE)
        )
        if new_price > max_covered:
            raise HTTPException(
                400,
                f"Your deposit only covers a price up to {max_covered:.0f}. "
                "Unlist and create a new listing to go higher.",
            )

    updated = (
        supabase.table("listings")
        .update({"price": float(new_price)})
        .eq("id", listing_id)
        .eq("status", "active")
        .execute()
    )
    if not updated.data:
        raise HTTPException(409, "Listing changed while you were editing it.")

    logger.info(
        "Listing %s repriced from %s to %s", listing_id, listing["price"], new_price,
        extra={"listing_id": listing_id},
    )
    return updated.data[0]


@router.post("/{listing_id}/unlist")
def unlist_listing(
    listing_id: str,
    claims:     dict = Depends(get_current_user),
):
    """
    Withdraw a listing and give the deposit back.

    Returning the deposit is the point. Unlisting used to only flip the status,
    which meant a seller who listed a ticket, changed their mind, and withdrew
    it before anyone bought lost 20% of the price for nothing. The deposit
    exists to protect a buyer who was let down; with no buyer there is nobody
    to protect and no reason to keep the money.
    """
    seller = get_user_by_clerk_id(claims["sub"])

    r = (
        supabase.table("listings")
        .update({"status": "cancelled"})
        .eq("id", listing_id)
        .eq("seller_id", seller["id"])
        .in_("status", ["active", "pending_fee"])
        .execute()
    )

    if not r.data:
        raise HTTPException(400, "Listing cannot be unlisted (it may be sold or locked).")

    listing = r.data[0]
    refunded = None

    # Only if one was actually paid and has not already been resolved. A
    # pending_fee listing never charged anything, so there is nothing to send
    # back. Non-fatal: the listing is already withdrawn, and a stuck deposit is
    # a reconciliation problem rather than a reason to fail the request.
    if listing.get("fee_razorpay_payment_id") and not deposits.is_resolved(listing):
        try:
            result = deposits.return_deposit(listing, reason="listing_withdrawn")
            refunded = result.get("amount_paise")
        except Exception:
            logger.exception(
                "Listing %s unlisted but the deposit was not returned", listing_id,
                extra={"listing_id": listing_id, "alert": True},
            )

    return {"status": "cancelled", "deposit_refunded_paise": refunded}


