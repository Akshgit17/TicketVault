from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from typing import List
from decimal import Decimal

from app.middleware.auth import get_current_user
from app.database import supabase
from app.services.qr import decode_qr, generate_fingerprint
from app.services.storage import upload_qr_image

router = APIRouter(prefix="/tickets", tags=["tickets"])


def _get_user(clerk_id: str) -> dict:
    r = supabase.table("users").select("id").eq("clerk_id", clerk_id).single().execute()
    if not r.data:
        raise HTTPException(status_code=404, detail="User not found. Call POST /users/me first.")
    return r.data


def _validate_city(city_id: str):
    r = supabase.table("cities").select("id").eq("id", city_id).eq("is_active", True).single().execute()
    if not r.data:
        raise HTTPException(status_code=400, detail="Invalid or inactive city.")


def _validate_event_city(event_id: str, city_id: str):
    r = supabase.table("events").select("city_id").eq("id", event_id).single().execute()
    if not r.data:
        raise HTTPException(status_code=404, detail="Event not found.")
    if r.data["city_id"] != city_id:
        raise HTTPException(status_code=400, detail="Event city does not match selected city.")


@router.post("/create")
async def create_ticket(
    event_id: str = Form(...),
    city_id: str = Form(...),
    price: Decimal = Form(...),
    original_price: Decimal = Form(...),
    qr_files: List[UploadFile] = File(...),
    claims: dict = Depends(get_current_user),
):
    seller = _get_user(claims["sub"])
    _validate_city(city_id)
    _validate_event_city(event_id, city_id)

    if price <= 0 or original_price <= 0:
        raise HTTPException(status_code=400, detail="Prices must be positive.")

    if len(qr_files) != 1:
        raise HTTPException(status_code=400, detail="Upload exactly 1 QR per ticket.")

    qr_file = qr_files[0]
    image_bytes = await qr_file.read()

    try:
        qr_data = decode_qr(image_bytes)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    fingerprint = generate_fingerprint(qr_data)

    dup = supabase.table("ticket_qrs").select("id").eq("fingerprint", fingerprint).execute()
    if dup.data:
        raise HTTPException(
            status_code=409,
            detail="Duplicate QR detected. This ticket has already been listed.",
        )

    storage_path = upload_qr_image(image_bytes, qr_file.content_type or "image/png")

    ticket_res = (
        supabase.table("tickets")
        .insert({
            "event_id": event_id,
            "seller_id": seller["id"],
            "city_id": city_id,
            "price": float(price),
            "original_price": float(original_price),
            "status": "available",
        })
        .execute()
    )
    ticket = ticket_res.data[0]

    supabase.table("ticket_qrs").insert({
        "ticket_id": ticket["id"],
        "qr_image_url": storage_path,
        "qr_data": qr_data,
        "fingerprint": fingerprint,
    }).execute()

    return {
        "ticket_id": ticket["id"],
        "listing_fee": round(float(price) * 0.20, 2),
        "status": "available",
    }


@router.get("")
async def list_tickets(
    city_id: str | None = None,
    event_id: str | None = None,
    claims: dict = Depends(get_current_user),
):
    query = (
        supabase.table("tickets")
        .select("*, events(name, date, venue), cities(name)")
        .eq("status", "available")
    )
    if city_id:
        query = query.eq("city_id", city_id)
    if event_id:
        query = query.eq("event_id", event_id)
    r = query.order("created_at", desc=True).execute()
    return r.data
