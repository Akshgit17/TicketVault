"""
Cancelling a concert.

The rule that matters, and the one most likely to be broken by someone tidying
this up later: **the seller is not at fault when a promoter calls off a show.**
So a cancellation returns deposits, where an SLA breach forfeits them. The two
paths look similar and do opposite things to the seller's money.
"""
import pytest

import app.services.deposits as deposits
import app.services.fulfillment as f
import app.services.ledger as ledger
import app.services.refunds as refunds
from app.config import LISTING_FEE_RATE
from app.services.payments import to_paise
from tests.conftest import BUYER, SELLER, make_booking, make_listing, patch_supabase
from tests.fake_supabase import FakeSupabase

PRICE = 50_000.0
DEPOSIT_PAISE = int(to_paise(PRICE) * LISTING_FEE_RATE)


class FakeRazorpay:
    def __init__(self):
        self.refund_calls = []

    class _Payment:
        def __init__(self, outer):
            self.outer = outer

        def refund(self, payment_id, params):
            self.outer.refund_calls.append((payment_id, params))
            return {"id": f"rfnd_{len(self.outer.refund_calls)}", "status": "processed"}

    @property
    def payment(self):
        return self._Payment(self)


def _listing(**overrides):
    l = make_listing(status="sold")
    l.update({
        "fee_razorpay_payment_id": "pay_deposit_1",
        "deposit_paid_paise":      DEPOSIT_PAISE,
        "deposit_returned_at":     None,
        "deposit_forfeited_at":    None,
    })
    l.update(overrides)
    return l


@pytest.fixture
def db(monkeypatch):
    booking = make_booking(payment_status="paid", total_price=PRICE)
    booking["razorpay_payment_id"] = "pay_booking_1"
    booking["fulfillment_status"] = f.AWAITING_TRANSFER

    fake = FakeSupabase({
        "users":    [dict(BUYER), dict(SELLER)],
        "listings": [_listing()],
        "bookings": [booking],
        "booking_events": [],
        "ledger_entries": [],
        "refunds":  [],
        "payouts":  [],
    })
    fake.unique["ledger_entries"] = ["idempotency_key"]
    patch_supabase(monkeypatch, fake)
    return fake


@pytest.fixture
def rzp(monkeypatch):
    fake = FakeRazorpay()
    monkeypatch.setattr(refunds, "client", fake)
    monkeypatch.setattr(deposits, "client", fake)
    return fake


# ── The rule that separates this from an SLA breach ───────────────────────────

def test_cancellation_returns_the_deposit_rather_than_forfeiting_it(db, rzp):
    """
    A promoter calling off a show is nothing to do with the seller, so fining
    them would be straightforwardly unfair. This is the single most important
    difference between cancellation and a missed transfer deadline.
    """
    listing = db.rows("listings")[0]

    deposits.return_deposit(listing, reason="event_cancelled")

    stored = db.rows("listings")[0]
    assert stored["deposit_returned_at"] is not None
    assert stored["deposit_forfeited_at"] is None

    kinds = {e["kind"] for e in db.rows("ledger_entries")}
    assert ledger.KIND_DEPOSIT_RETURN in kinds
    assert ledger.KIND_FORFEIT not in kinds, "the seller did nothing wrong"
    assert ledger.KIND_COMPENSATION not in kinds, "nobody is being compensated by a seller"


def test_buyer_is_refunded_in_full(db, rzp):
    booking = db.rows("bookings")[0]

    refunds.refund_booking(booking, reason="event_cancelled")

    assert db.rows("bookings")[0]["payment_status"] == "refunded"
    refund_entries = [
        e for e in db.rows("ledger_entries") if e["kind"] == ledger.KIND_REFUND
    ]
    assert len(refund_entries) == 1
    assert int(refund_entries[0]["amount_paise"]) == to_paise(PRICE)


def test_a_cancelled_event_nets_to_zero(db, rzp):
    """The same invariant as every other terminal path."""
    listing = db.rows("listings")[0]
    booking = db.rows("bookings")[0]

    ledger.record_capture(booking["id"], BUYER["id"], to_paise(PRICE), "pay_booking_1")
    deposits.record_deposit_paid(listing, "pay_deposit_1")

    refunds.refund_booking(booking, reason="event_cancelled")
    deposits.return_deposit(db.rows("listings")[0], reason="event_cancelled")

    assert ledger.settlement_balance_paise(booking["id"], listing["id"]) == 0


# ── Idempotency and edge cases ────────────────────────────────────────────────

def test_returning_a_deposit_twice_refunds_once(db, rzp):
    deposits.return_deposit(db.rows("listings")[0], reason="event_cancelled")
    again = deposits.return_deposit(db.rows("listings")[0], reason="event_cancelled")

    assert again["status"] == "already_returned"
    assert len(rzp.refund_calls) == 1


def test_an_already_forfeited_deposit_is_not_returned(db, rzp):
    """
    A seller who already missed the deadline before the event was cancelled
    does not get rescued by the cancellation. The forfeit already happened and
    a buyer was already compensated from it.
    """
    db.rows("listings")[0]["deposit_forfeited_at"] = "2026-08-01T00:00:00+00:00"

    with pytest.raises(deposits.DepositError) as e:
        deposits.return_deposit(db.rows("listings")[0], reason="event_cancelled")

    assert e.value.code == "already_forfeited"
    assert rzp.refund_calls == []


def test_a_booking_that_is_not_paid_cannot_be_refunded(db, rzp):
    """
    The guard the cancel path relies on. Money already paid out cannot be
    clawed back from here, so the endpoint skips released bookings and reports
    them as `already_paid_out` rather than pretending it reversed something.
    """
    booking = dict(db.rows("bookings")[0])
    booking["payment_status"] = "pending"

    with pytest.raises(refunds.RefundError) as e:
        refunds.refund_booking(booking, reason="event_cancelled")

    assert e.value.code == "not_refundable"
    assert rzp.refund_calls == []


def test_refunding_twice_only_refunds_once(db, rzp):
    """Cancellation may be retried, so the buyer must not be paid twice."""
    booking = db.rows("bookings")[0]

    refunds.refund_booking(booking, reason="event_cancelled")
    again = refunds.refund_booking(db.rows("bookings")[0], reason="event_cancelled")

    assert again["status"] == "already_refunded"
    assert len(rzp.refund_calls) == 1


def test_cancel_event_route_handler(db, rzp):
    """Ensure the cancel_event route function executes without NameError or scope issues."""
    import app.routes.admin as admin_route
    from app.routes.admin import CancelEventRequest

    # Add an event row to fake supabase
    db.tables["events"] = [{
        "id": "evt_123",
        "title": "Test Concert",
        "date": "2026-09-01T20:00:00Z",
        "cancelled_at": None,
    }]

    admin_user = {"id": "usr_admin", "role": "admin"}
    req = CancelEventRequest(reason="Promoter cancelled show")
    res = admin_route.cancel_event("evt_123", req, admin=admin_user)

    assert res["status"] == "cancelled"
    assert res["event_id"] == "evt_123"
    assert db.rows("events")[0]["cancelled_at"] is not None
    assert db.rows("events")[0]["cancellation_reason"] == "Promoter cancelled show"

