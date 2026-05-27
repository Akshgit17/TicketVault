"""
Auto-confirm cron job.
Runs every 5 minutes via APScheduler.
Auto-confirms paid orders where buyer did not act within 2 hours.
"""
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.database import supabase

UTC = timezone.utc


def run_auto_confirm():
    now = datetime.now(UTC).isoformat()

    # Fetch paid bookings that have passed their confirmation deadline
    r = (
        supabase.table("bookings")
        .select("*, listings(id, seller_id, price)")
        .eq("payment_status", "paid")
        .eq("confirmation_status", "pending")
        .lt("confirmation_deadline", now)
        .execute()
    )

    bookings = r.data or []
    confirmed = []

    for booking in bookings:
        try:
            # 1. Update booking status
            supabase.table("bookings").update({
                "confirmation_status": "auto_confirmed",
            }).eq("id", booking["id"]).execute()

            # 2. Ensure listing is marked as sold (it should already be, but safe to keep)
            listing_id = booking["listing_id"]
            supabase.table("listings").update({
                "status": "sold",
            }).eq("id", listing_id).execute()

            # Note: In a real system, you'd trigger a payout to the seller here.
            # For now, we just mark it as auto-confirmed.

            confirmed.append(booking["id"])

        except Exception as e:
            print(f"[auto_confirm] Failed for booking {booking['id']}: {e}")

    if confirmed:
        print(f"[auto_confirm] Auto-confirmed {len(confirmed)} bookings.")
    return confirmed


scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app):
    scheduler.add_job(run_auto_confirm, "interval", minutes=5, id="auto_confirm")
    scheduler.start()
    print("[scheduler] Auto-confirm job started.")
    yield
    scheduler.shutdown()
