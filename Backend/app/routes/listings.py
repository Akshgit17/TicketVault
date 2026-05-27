from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from decimal import Decimal
from typing import List
from pydantic import BaseModel
from postgrest.exceptions import APIError

from app.middleware.auth import get_current_user
from app.services.user_service import get_user_by_clerk_id
from app.database import supabase
from app.services.qr import decode_qr, generate_fingerprint
from app.services.storage import upload_qr_image

from app.services.razorpay import create_order, verify_payment
from app.config import settings

router = APIRouter(prefix="/listings", tags=["listings"])


def _validate_city(city_id: str):
    r = supabase.table("cities").select("id").eq("id", city_id).eq("is_active", True).execute()
    if not r.data:
        raise HTTPException(400, "Invalid or inactive city.")


def _validate_event_city(event_id: str, city_id: str):
    r = supabase.table("events").select("city_id").eq("id", event_id).execute()
    if not r.data:
        raise HTTPException(404, "Event not found.")
    if r.data[0]["city_id"] != city_id:
        raise HTTPException(400, "Event city does not match selected city.")


# ── GET listings (public — no auth) ──────────────────────────────────────────

@router.get("")
async def list_listings(
    city_id:  str | None = None,
    event_id: str | None = None,
):
    q = (
        supabase.table("listings")
        .select("""
            *,
            events(id, title, date, venue, image_url),
            cities(name)
        """)
        .eq("status", "active")
    )
    if city_id:
        q = q.eq("city_id", city_id)
    if event_id:
        q = q.eq("event_id", event_id)

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
async def initiate_listing_fee(
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

    fee_amount = float(listing["price"]) * 0.20
    
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
    except Exception as e:
        raise HTTPException(500, f"Razorpay error: {e}")

@router.post("/{listing_id}/verify-fee")
async def verify_listing_fee(
    listing_id: str,
    body:       VerifyFeeRequest,
    claims:     dict = Depends(get_current_user),
):
    seller = get_user_by_clerk_id(claims["sub"])
    
    # Verify signature
    is_valid = verify_payment(
        razorpay_order_id=body.razorpay_order_id,
        razorpay_payment_id=body.razorpay_payment_id,
        razorpay_signature=body.razorpay_signature,
    )
    
    if not is_valid:
        raise HTTPException(400, "Invalid payment signature.")
        
    # Update listing to active
    r = (
        supabase.table("listings")
        .update({
            "status":                  "active",
            "fee_razorpay_payment_id": body.razorpay_payment_id,
        })
        .eq("id", listing_id)
        .eq("seller_id", seller["id"])
        .execute()
    )
    
    if not r.data:
        raise HTTPException(404, "Listing not found or not yours.")
        
    return {"status": "active"}


# ── GET my listings (auth required) ──────────────────────────────────────────

@router.get("/my/all")
async def my_listings(claims: dict = Depends(get_current_user)):
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
async def get_listing(listing_id: str):
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
    print(f"[DEBUG] create_listing: event_id={event_id}, city_id={city_id}, price={price}, original_price={original_price}, quantity={quantity}")
    
    # Cast manually to avoid 422s from Pydantic before we can log
    try:
        d_price = Decimal(price)
        d_orig  = Decimal(original_price)
        i_qty   = int(quantity)
    except Exception as e:
        raise HTTPException(422, f"Invalid numeric value: {e}")

    seller = get_user_by_clerk_id(claims["sub"])
    _validate_city(city_id)
    _validate_event_city(event_id, city_id)

    # Calculate fee for metadata
    fee_amount = float(d_price * Decimal("0.20"))

    if d_price <= 0 or d_orig <= 0:
        raise HTTPException(400, "Prices must be positive.")
    if i_qty < 1:
        raise HTTPException(400, "Quantity must be at least 1.")

    image_bytes = await qr_file.read()
    try:
        qr_data = decode_qr(image_bytes)
    except Exception as e:
        raise HTTPException(422, str(e))

    qr_fingerprint = generate_fingerprint(qr_data)

    # Duplicate check (ignore cancelled listings)
    dup = supabase.table("listings").select("id").eq("qr_fingerprint", qr_fingerprint).neq("status", "cancelled").execute()
    if dup.data:
        raise HTTPException(409, "Duplicate QR detected. This ticket is already actively listed or sold.")

    qr_url = upload_qr_image(image_bytes, qr_file.content_type or "image/png")

    listing_res = supabase.table("listings").insert({
        "event_id":       event_id,
        "seller_id":      seller["id"],
        "city_id":        city_id,
        "price":          float(d_price),
        "original_price": float(d_orig),
        "quantity":       i_qty,
        "status":         "pending_fee", # Start as pending_fee
        "qr_image_url":   qr_url,
        "qr_fingerprint": qr_fingerprint,
    }).execute()

    listing = listing_res.data[0]
    return {
        "listing_id":  listing["id"],
        "status":      "pending_fee",
        "listing_fee": fee_amount,
    }


# ── UNLIST ───────────────────────────────────────────────────────────────────

@router.post("/{listing_id}/unlist")
async def unlist_listing(
    listing_id: str,
    claims:     dict = Depends(get_current_user),
):
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
        
    return {"status": "cancelled"}


