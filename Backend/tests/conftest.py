"""
Test configuration.

Environment defaults are set before any app import so the suite runs without a
.env file (e.g. in CI). Nothing here touches the real Supabase or Razorpay.
"""
import os

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("CLERK_JWT_ISSUER", "https://test.clerk.dev")
os.environ.setdefault("RAZORPAY_KEY_ID", "rzp_test_key")
os.environ.setdefault("RAZORPAY_KEY_SECRET", "rzp_test_secret")
os.environ.setdefault("RAZORPAY_WEBHOOK_SECRET", "whsec_test")
os.environ.setdefault("CRON_SECRET", "cron-test")

import pytest  # noqa: E402

from tests.fake_supabase import FakeSupabase  # noqa: E402


# ── Domain fixtures ───────────────────────────────────────────────────────────

SELLER = {"id": "user-seller", "clerk_id": "clerk_seller", "name": "Seller", "email": "s@x.com"}
BUYER = {"id": "user-buyer", "clerk_id": "clerk_buyer", "name": "Buyer", "email": "b@x.com"}
ATTACKER = {"id": "user-attacker", "clerk_id": "clerk_attacker", "name": "Mallory", "email": "m@x.com"}


def make_listing(listing_id="listing-expensive", price=50000.0, status="active", seller_id=SELLER["id"]):
    return {
        "id": listing_id,
        "event_id": "event-1",
        "seller_id": seller_id,
        "city_id": "city-1",
        "price": price,
        "original_price": price,
        "quantity": 1,
        "status": status,
        "locked_by": None,
        "lock_expiry": None,
        "qr_image_url": "qrs/abc.png",
        "qr_fingerprint": f"fp-{listing_id}",
        "fee_razorpay_order_id": None,
        "fee_razorpay_payment_id": None,
    }


def make_booking(
    booking_id="booking-1",
    listing_id="listing-expensive",
    user_id=BUYER["id"],
    total_price=50000.0,
    order_id="order_expensive",
    payment_status="pending",
):
    return {
        "id": booking_id,
        "user_id": user_id,
        "listing_id": listing_id,
        "quantity": 1,
        "total_price": total_price,
        "payment_status": payment_status,
        "razorpay_order_id": order_id,
        "razorpay_payment_id": None,
        "confirmation_status": "pending",
        "confirmation_deadline": None,
        # Mirrors the NOT NULL DEFAULT from migration 005. Without it the fake
        # rows lack a column real rows always have, and status-guarded updates
        # find nothing to match.
        "fulfillment_status": "not_started",
        "transfer_deadline": None,
        "escrow_release_at": None,
    }


def patch_supabase(monkeypatch, fake) -> None:
    """
    Point every module that holds a `supabase` reference at the fake.

    Modules bind `from app.database import supabase` at import time, so each
    holds its own reference. Patching them individually per test is a trap:
    adding a new caller (settlement -> ledger) silently leaves it talking to the
    real database, and the failure surfaces as a DNS error rather than an
    obvious mistake. Walking the package keeps that from recurring.
    """
    import importlib
    import pkgutil

    import app

    for info in pkgutil.walk_packages(app.__path__, prefix="app."):
        try:
            module = importlib.import_module(info.name)
        except Exception:
            continue
        if hasattr(module, "supabase"):
            monkeypatch.setattr(module, "supabase", fake, raising=False)


@pytest.fixture
def db():
    """A fake Supabase seeded with a buyer, a seller, and one expensive listing."""
    return FakeSupabase(
        {
            "users": [dict(SELLER), dict(BUYER), dict(ATTACKER)],
            "listings": [make_listing()],
            "bookings": [],
            "events": [{"id": "event-1", "title": "Test Show", "city_id": "city-1"}],
            "cities": [{"id": "city-1", "name": "Bangalore", "slug": "bangalore", "is_active": True}],
        }
    )
