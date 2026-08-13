"""
Phase 1.3 — Razorpay webhook handling.

The webhook is authoritative: a buyer who closes the tab after paying never
calls /bookings/verify-payment, so without this their money is taken and the
booking stays pending forever.

Delivery order is not guaranteed and duplicates are expected, so these tests
focus on idempotency and on refusing to settle wrong amounts.
"""
import json

import pytest

import app.routes.webhooks as wh
from app.services.settlement import SettlementError
from tests.conftest import make_booking, make_listing, patch_supabase
from tests.fake_supabase import FakeSupabase


@pytest.fixture
def db(monkeypatch):
    fake = FakeSupabase({
        "bookings": [make_booking(total_price=50000.0, order_id="order_book")],
        "listings": [make_listing(status="locked")],
        "webhook_events": [],
        "ledger_entries": [],
    })
    fake.unique["ledger_entries"] = ["idempotency_key"]
    patch_supabase(monkeypatch, fake)
    return fake


def payment_captured(order_id="order_book", payment_id="pay_1", amount=5_000_000):
    return {
        "event": "payment.captured",
        "payload": {"payment": {"entity": {
            "id": payment_id, "order_id": order_id, "amount": amount, "status": "captured",
        }}},
    }


# ── Signature handling ────────────────────────────────────────────────────────

def _signed_client(db):
    """A TestClient over just the webhook router — avoids booting the scheduler."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(wh.router)
    return TestClient(app)


def _sign(raw: bytes) -> str:
    """Reproduce Razorpay's webhook signature: HMAC-SHA256(raw_body, secret)."""
    import hmac
    import hashlib

    from app.config import settings

    return hmac.new(
        settings.RAZORPAY_WEBHOOK_SECRET.encode(),
        raw,
        hashlib.sha256,
    ).hexdigest()


def test_endpoint_rejects_a_forged_signature(db):
    client = _signed_client(db)
    raw = json.dumps(payment_captured()).encode()

    resp = client.post(
        "/webhooks/razorpay",
        content=raw,
        headers={"x-razorpay-signature": "forged", "x-razorpay-event-id": "evt_forged"},
    )

    assert resp.status_code == 400
    assert db.get("bookings", "booking-1")["payment_status"] == "pending"


def test_endpoint_settles_on_a_genuine_signature(db):
    """Full path: real HMAC, real route, real settlement."""
    client = _signed_client(db)
    raw = json.dumps(payment_captured()).encode()

    resp = client.post(
        "/webhooks/razorpay",
        content=raw,
        headers={"x-razorpay-signature": _sign(raw), "x-razorpay-event-id": "evt_ok"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "processed"
    assert db.get("bookings", "booking-1")["payment_status"] == "paid"


def test_endpoint_dedupes_repeated_event_id(db):
    """Razorpay retries on any non-2xx; the same event id must settle once."""
    client = _signed_client(db)
    raw = json.dumps(payment_captured()).encode()
    headers = {"x-razorpay-signature": _sign(raw), "x-razorpay-event-id": "evt_dupe"}

    first = client.post("/webhooks/razorpay", content=raw, headers=headers)
    second = client.post("/webhooks/razorpay", content=raw, headers=headers)

    assert first.json()["status"] == "processed"
    assert second.json()["status"] == "duplicate"
    assert len([e for e in db.rows("webhook_events") if e["event_id"] == "evt_dupe"]) == 1


def test_signature_uses_raw_body(monkeypatch):
    """
    Razorpay signs the exact bytes it sent. Re-serialising the parsed JSON
    changes key order and whitespace, which silently breaks verification.
    """
    seen = {}

    class FakeUtility:
        def verify_webhook_signature(self, body, signature, secret):
            seen["body"] = body
            return True

    monkeypatch.setattr(wh.client, "utility", FakeUtility(), raising=False)
    raw = b'{"event":"payment.captured",  "spaced": true}'
    assert wh._verify_signature(raw, "sig") is True
    assert seen["body"] == raw.decode()


# ── Settlement via webhook ────────────────────────────────────────────────────

def test_captured_payment_settles_booking(db):
    result = wh._handle("payment.captured", payment_captured())

    assert result["status"] == "paid"
    booking = db.get("bookings", "booking-1")
    assert booking["payment_status"] == "paid"
    assert booking["razorpay_payment_id"] == "pay_1"
    assert db.get("listings", "listing-expensive")["status"] == "sold"


def test_webhook_settles_when_client_never_returns(db):
    """The core reason this endpoint exists: buyer closes the tab after paying."""
    assert db.get("bookings", "booking-1")["payment_status"] == "pending"
    wh._handle("payment.captured", payment_captured())
    assert db.get("bookings", "booking-1")["payment_status"] == "paid"


def test_duplicate_delivery_is_idempotent(db):
    first = wh._handle("payment.captured", payment_captured())
    second = wh._handle("payment.captured", payment_captured())

    assert first["status"] == "paid"
    assert second["status"] == "already_paid"
    assert db.get("bookings", "booking-1")["razorpay_payment_id"] == "pay_1"


def test_wrong_amount_is_refused(db):
    """A signed webhook is still not permission to settle for the wrong amount."""
    with pytest.raises(SettlementError) as e:
        wh._handle("payment.captured", payment_captured(amount=100))   # 1 rupee

    assert e.value.code == "amount_mismatch"
    assert db.get("bookings", "booking-1")["payment_status"] == "pending"


def test_failed_payment_releases_the_listing(db):
    payload = {
        "event": "payment.failed",
        "payload": {"payment": {"entity": {
            "id": "pay_f", "order_id": "order_book", "amount": 5_000_000, "status": "failed",
        }}},
    }
    wh._handle("payment.failed", payload)

    assert db.get("bookings", "booking-1")["payment_status"] == "failed"
    assert db.get("listings", "listing-expensive")["status"] == "active"


def test_late_failure_cannot_unsell_a_settled_booking(db):
    """Out-of-order delivery: captured lands first, a stale failure arrives after."""
    wh._handle("payment.captured", payment_captured())

    wh._handle("payment.failed", {
        "event": "payment.failed",
        "payload": {"payment": {"entity": {
            "id": "pay_f", "order_id": "order_book", "amount": 5_000_000,
        }}},
    })

    assert db.get("bookings", "booking-1")["payment_status"] == "paid"
    assert db.get("listings", "listing-expensive")["status"] == "sold"


def test_unknown_order_is_acknowledged_not_retried(db):
    result = wh._handle("payment.captured", payment_captured(order_id="order_nonexistent"))
    assert result["status"] == "ignored"
    assert result["reason"] == "unknown_order"


def test_listing_fee_webhook_activates_listing(db):
    db.rows("listings").append(
        {**make_listing("listing-fee", price=1000.0, status="pending_fee"),
         "fee_razorpay_order_id": "order_fee"}
    )

    result = wh._handle("payment.captured", payment_captured(
        order_id="order_fee", payment_id="pay_fee", amount=20_000,
    ))

    assert result["status"] == "active"
    assert db.get("listings", "listing-fee")["status"] == "active"


# ── Deduplication bookkeeping ─────────────────────────────────────────────────

def test_already_processed_detects_replay(db):
    assert wh._already_processed("evt_1") is False
    wh._record_event("evt_1", "payment.captured", {}, "processed")
    assert wh._already_processed("evt_1") is True


def test_fallback_event_id_when_header_missing():
    eid = wh._fallback_event_id(payment_captured(payment_id="pay_xyz"))
    assert eid == "payment.captured:pay_xyz"
    assert wh._fallback_event_id({"event": "x", "payload": {}}) is None
