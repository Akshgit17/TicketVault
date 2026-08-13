"""
Phase 1.2 regression tests.

The vulnerability these lock down:

    /bookings/verify-payment verified the Razorpay signature over a *client
    supplied* order id and never compared it to the booking's own order, nor
    checked the amount. An attacker could pay 1 rupee on a listing they own,
    then replay that genuine receipt against a booking for a 50,000 rupee
    ticket. The signature validates, because the payment is real — it just
    settles a different order.
"""
import pytest

from app.services.payments import (
    PaymentVerificationError,
    to_paise,
    verify_payment_for,
)


# ── Test doubles ──────────────────────────────────────────────────────────────

class FakeRazorpayOrders:
    def __init__(self, orders):
        self._orders = orders
        self.fetch_calls = []

    def fetch(self, order_id):
        self.fetch_calls.append(order_id)
        if order_id not in self._orders:
            raise RuntimeError(f"no such order {order_id}")
        return self._orders[order_id]


@pytest.fixture
def rzp(monkeypatch):
    """
    Two real, genuinely-paid orders: a cheap one the attacker controls and an
    expensive one they want. Every signature is treated as cryptographically
    valid, which is the attacker's actual position — they hold a real receipt.
    """
    orders = {
        "order_cheap":     {"id": "order_cheap",     "status": "paid", "amount": to_paise(1.0)},
        "order_expensive": {"id": "order_expensive", "status": "paid", "amount": to_paise(50000.0)},
        "order_created":   {"id": "order_created",   "status": "created", "amount": to_paise(50000.0)},
    }
    fake_orders = FakeRazorpayOrders(orders)

    import app.services.payments as payments

    monkeypatch.setattr(payments.client, "order", fake_orders, raising=False)
    monkeypatch.setattr(payments, "verify_payment", lambda **kw: True)
    return fake_orders


# ── The exploit ───────────────────────────────────────────────────────────────

def test_receipt_from_another_order_is_rejected(rzp):
    """THE exploit: a real 1-rupee receipt must not settle a 50,000 rupee booking."""
    with pytest.raises(PaymentVerificationError) as e:
        verify_payment_for(
            expected_order_id="order_expensive",
            expected_amount_paise=to_paise(50000.0),
            razorpay_order_id="order_cheap",          # attacker's own paid order
            razorpay_payment_id="pay_cheap",
            razorpay_signature="valid-signature",
        )
    assert e.value.code == "order_mismatch"
    # Rejected before we ever call out to Razorpay.
    assert rzp.fetch_calls == []


def test_equal_priced_receipt_is_rejected(rzp):
    """
    The case the amount check alone cannot catch, and the reason order binding
    is not redundant: two listings at the same price. The attacker buys their
    own 50,000 rupee listing, then replays that receipt against someone else's
    50,000 rupee listing. Amounts match perfectly — only the order id differs.
    """
    rzp._orders["order_attacker_own"] = {
        "id": "order_attacker_own",
        "status": "paid",
        "amount": to_paise(50000.0),
    }
    with pytest.raises(PaymentVerificationError) as e:
        verify_payment_for(
            expected_order_id="order_expensive",
            expected_amount_paise=to_paise(50000.0),
            razorpay_order_id="order_attacker_own",
            razorpay_payment_id="pay_attacker",
            razorpay_signature="valid-signature",
        )
    assert e.value.code == "order_mismatch"


def test_amount_is_verified_server_side(rzp):
    """
    Even with the correct order id, the amount must come from Razorpay — never
    from the booking row alone if they disagree.
    """
    with pytest.raises(PaymentVerificationError) as e:
        verify_payment_for(
            expected_order_id="order_cheap",
            expected_amount_paise=to_paise(50000.0),   # we expected 50k
            razorpay_order_id="order_cheap",           # but this order is for 1 rupee
            razorpay_payment_id="pay_cheap",
            razorpay_signature="valid-signature",
        )
    assert e.value.code == "amount_mismatch"


def test_unpaid_order_is_rejected(rzp):
    with pytest.raises(PaymentVerificationError) as e:
        verify_payment_for(
            expected_order_id="order_created",
            expected_amount_paise=to_paise(50000.0),
            razorpay_order_id="order_created",
            razorpay_payment_id="pay_x",
            razorpay_signature="valid-signature",
        )
    assert e.value.code == "order_not_paid"


def test_invalid_signature_is_rejected(rzp, monkeypatch):
    import app.services.payments as payments

    monkeypatch.setattr(payments, "verify_payment", lambda **kw: False)
    with pytest.raises(PaymentVerificationError) as e:
        verify_payment_for(
            expected_order_id="order_expensive",
            expected_amount_paise=to_paise(50000.0),
            razorpay_order_id="order_expensive",
            razorpay_payment_id="pay_forged",
            razorpay_signature="forged",
        )
    assert e.value.code == "invalid_signature"


def test_record_with_no_order_cannot_be_settled(rzp):
    """A record that never initiated payment must not be settleable at all."""
    with pytest.raises(PaymentVerificationError) as e:
        verify_payment_for(
            expected_order_id=None,
            expected_amount_paise=to_paise(50000.0),
            razorpay_order_id="order_cheap",
            razorpay_payment_id="pay_cheap",
            razorpay_signature="valid-signature",
        )
    assert e.value.code == "no_order"


def test_provider_outage_fails_closed(rzp, monkeypatch):
    """If Razorpay is unreachable we must refuse to settle, not assume success."""
    def boom(_):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(rzp, "fetch", boom)
    with pytest.raises(PaymentVerificationError) as e:
        verify_payment_for(
            expected_order_id="order_expensive",
            expected_amount_paise=to_paise(50000.0),
            razorpay_order_id="order_expensive",
            razorpay_payment_id="pay_ok",
            razorpay_signature="valid-signature",
        )
    assert e.value.code == "verification_unavailable"


# ── The happy path still works ────────────────────────────────────────────────

def test_matching_order_and_amount_succeeds(rzp):
    order = verify_payment_for(
        expected_order_id="order_expensive",
        expected_amount_paise=to_paise(50000.0),
        razorpay_order_id="order_expensive",
        razorpay_payment_id="pay_legit",
        razorpay_signature="valid-signature",
    )
    assert order["status"] == "paid"
    assert rzp.fetch_calls == ["order_expensive"]


def test_to_paise_matches_order_creation_rounding():
    """create_order uses int(round(x * 100)); comparisons must round identically."""
    assert to_paise(1.0) == 100
    assert to_paise(50000.0) == 5_000_000
    assert to_paise(1999.99) == 199999
    assert to_paise(0.1 + 0.2) == 30      # float noise must not shift the paise value
