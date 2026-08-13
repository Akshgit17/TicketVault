"""
Dispute resolution.

A dispute freezes a seller's payout, so the thing that matters is that the
freeze can actually be lifted, in both directions, by a human. Without a
resolution path a false claim stalls an honest seller forever, which is a worse
failure than the dispute it was meant to handle.

These exercise the service layer the admin route calls, rather than the route
itself, because the money movement is what needs pinning.
"""
import pytest

import app.jobs.fulfillment_jobs as jobs
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


def _disputed_booking():
    b = make_booking(payment_status="paid", total_price=PRICE)
    b["fulfillment_status"] = f.TRANSFER_CONFIRMED
    b["confirmation_status"] = "disputed"
    b["razorpay_payment_id"] = "pay_booking_1"
    b["escrow_release_at"] = "2020-01-01T00:00:00+00:00"
    return b


def _listing():
    l = make_listing(status="sold")
    l.update({
        "fee_razorpay_payment_id": "pay_deposit_1",
        "deposit_paid_paise":      DEPOSIT_PAISE,
        "deposit_returned_at":     None,
        "deposit_forfeited_at":    None,
        "deposit_forfeit_reason":  None,
    })
    return l


@pytest.fixture
def db(monkeypatch):
    fake = FakeSupabase({
        "users":    [dict(BUYER), {**SELLER, "razorpay_linked_account_id": "acc_1"}],
        "listings": [_listing()],
        "bookings": [_disputed_booking()],
        "booking_events": [],
        "ledger_entries": [],
        "refunds":  [],
        "payouts":  [],
    })
    fake.unique["ledger_entries"] = ["idempotency_key"]
    fake.unique["payouts"] = ["booking_id"]
    patch_supabase(monkeypatch, fake)
    return fake


@pytest.fixture
def rzp(monkeypatch):
    fake = FakeRazorpay()
    monkeypatch.setattr(refunds, "client", fake)
    monkeypatch.setattr(deposits, "client", fake)
    return fake


# ── The freeze ────────────────────────────────────────────────────────────────

def test_dispute_blocks_payout_until_resolved(db, monkeypatch):
    """The premise. If this fails, nothing else on this page matters."""
    released = jobs.release_due_escrow()
    assert released["released"] == []


def test_clearing_the_dispute_releases_the_payout(db, monkeypatch, rzp):
    """Rejecting a claim must actually unfreeze the money."""
    paid = []
    monkeypatch.setattr(
        "app.services.payouts.release_payout",
        lambda booking, listing: paid.append(booking["id"]),
    )

    # What the admin route does on `reject`.
    db.get("bookings", "booking-1")["confirmation_status"] = "confirmed"

    jobs.release_due_escrow()
    assert paid == ["booking-1"], "a rejected dispute must let the seller be paid"


# ── Upholding ─────────────────────────────────────────────────────────────────

def test_upholding_treats_the_buyer_like_an_sla_breach(db, rzp):
    """
    An upheld dispute and a missed deadline end the same way for the buyer:
    they paid and did not get a usable ticket, so they are refunded and
    compensated from the seller's deposit.
    """
    booking = db.get("bookings", "booking-1")
    listing = db.rows("listings")[0]

    f.fail_fulfillment(booking, reason="dispute upheld", actor="admin", actor_id="admin-1")
    refunds.refund_booking(booking, reason="dispute_upheld")
    deposits.forfeit_deposit(listing, booking, reason="dispute_upheld")

    assert db.get("bookings", "booking-1")["fulfillment_status"] == f.FAILED

    kinds = {e["kind"] for e in db.rows("ledger_entries")}
    assert ledger.KIND_REFUND in kinds
    assert ledger.KIND_COMPENSATION in kinds
    assert ledger.KIND_FORFEIT in kinds


def test_confirmed_booking_may_still_be_failed(db):
    """
    The transition an upheld dispute depends on.

    A buyer can confirm receipt and only afterwards discover the ticket is for
    the wrong date, so `transfer_confirmed` must not be a one way door into
    payout.
    """
    assert f.FAILED in f.ALLOWED[f.TRANSFER_CONFIRMED]


def test_upheld_dispute_cannot_also_return_the_deposit(db, rzp):
    """A deposit is returned XOR forfeited, never both."""
    booking = db.get("bookings", "booking-1")
    listing = db.rows("listings")[0]

    deposits.forfeit_deposit(listing, booking, reason="dispute_upheld")

    with pytest.raises(deposits.DepositError) as e:
        deposits.return_deposit(db.rows("listings")[0])
    assert e.value.code == "already_forfeited"
