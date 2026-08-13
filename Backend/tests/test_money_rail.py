"""
Phase 2 — ledger, refunds, payouts, reconciliation.

The invariant these are built around: a fully settled booking's ledger entries
net to zero. Money in must equal money out, or it is unaccounted for.
"""
import pytest

import app.jobs.reconcile as reconcile
import app.services.ledger as ledger
import app.services.payouts as payouts
import app.services.refunds as refunds
from app.services.payments import to_paise
from tests.conftest import BUYER, SELLER, make_booking, make_listing, patch_supabase
from tests.fake_supabase import FakeSupabase


@pytest.fixture
def db(monkeypatch):
    fake = FakeSupabase({
        "users": [
            dict(BUYER),
            {**SELLER, "razorpay_linked_account_id": "acc_seller1", "payout_hold": False},
        ],
        "listings": [make_listing(status="sold")],
        "bookings": [make_booking(payment_status="paid", total_price=50000.0)],
        "ledger_entries": [],
        "payouts": [],
        "refunds": [],
    })
    fake.unique["ledger_entries"] = ["idempotency_key"]
    fake.unique["payouts"] = ["booking_id"]

    patch_supabase(monkeypatch, fake)
    return fake


class FakeRazorpay:
    def __init__(self):
        self.refund_calls = []
        self.transfer_calls = []

    class _Payment:
        def __init__(self, outer):
            self.outer = outer

        def refund(self, payment_id, params):
            self.outer.refund_calls.append((payment_id, params))
            return {"id": f"rfnd_{len(self.outer.refund_calls)}", "status": "processed"}

    class _Transfer:
        def __init__(self, outer):
            self.outer = outer

        def create(self, params):
            self.outer.transfer_calls.append(params)
            return {"id": f"trf_{len(self.outer.transfer_calls)}", "status": "processed"}

    @property
    def payment(self):
        return self._Payment(self)

    @property
    def transfer(self):
        return self._Transfer(self)


@pytest.fixture
def rzp(monkeypatch):
    fake = FakeRazorpay()
    monkeypatch.setattr(refunds, "client", fake)
    monkeypatch.setattr(payouts, "client", fake)
    return fake


# ── Ledger fundamentals ───────────────────────────────────────────────────────

def test_capture_is_recorded_once_per_payment(db):
    first = ledger.record_capture("booking-1", BUYER["id"], 5_000_000, "pay_abc")
    second = ledger.record_capture("booking-1", BUYER["id"], 5_000_000, "pay_abc")

    assert first is not None
    assert second is None, "the same payment must not be booked twice"
    assert len(db.rows("ledger_entries")) == 1


def test_ledger_rejects_non_positive_amounts(db):
    for bad in (0, -1):
        with pytest.raises(ValueError):
            ledger.record(
                kind=ledger.KIND_CAPTURE, direction=ledger.DIRECTION_IN,
                amount_paise=bad, idempotency_key=f"x{bad}", booking_id="booking-1",
            )


def test_settled_booking_nets_to_zero(db):
    """capture in == payout out + fee out."""
    ledger.record_capture("booking-1", BUYER["id"], 5_000_000, "pay_1")
    ledger.record_payout("booking-1", SELLER["id"], 4_750_000, "trf_1")
    ledger.record_fee("booking-1", 250_000, "payout:trf_1")

    assert ledger.booking_balance_paise("booking-1") == 0


def test_refunded_booking_nets_to_zero(db):
    ledger.record_capture("booking-1", BUYER["id"], 5_000_000, "pay_1")
    ledger.record_refund("booking-1", BUYER["id"], 5_000_000, "rfnd_1")

    assert ledger.booking_balance_paise("booking-1") == 0


def test_unsettled_booking_shows_platform_holding_funds(db):
    ledger.record_capture("booking-1", BUYER["id"], 5_000_000, "pay_1")
    # Money is in, nothing has gone out — the platform owes it to someone.
    assert ledger.booking_balance_paise("booking-1") == 5_000_000


# ── Refunds ───────────────────────────────────────────────────────────────────

def test_refund_returns_money_and_writes_ledger(db, rzp):
    booking = db.get("bookings", "booking-1")
    booking["razorpay_payment_id"] = "pay_1"
    ledger.record_capture("booking-1", BUYER["id"], 5_000_000, "pay_1")

    result = refunds.refund_booking(booking, reason="seller failed to transfer")

    assert result["status"] == "refunded"
    assert rzp.refund_calls[0][0] == "pay_1"
    assert rzp.refund_calls[0][1]["amount"] == 5_000_000
    assert db.get("bookings", "booking-1")["payment_status"] == "refunded"
    assert ledger.booking_balance_paise("booking-1") == 0


def test_unpaid_booking_cannot_be_refunded(db, rzp):
    booking = db.get("bookings", "booking-1")
    booking["payment_status"] = "pending"

    with pytest.raises(refunds.RefundError) as e:
        refunds.refund_booking(booking, reason="nope")

    assert e.value.code == "not_refundable"
    assert rzp.refund_calls == []


def test_cannot_refund_more_than_captured(db, rzp):
    booking = db.get("bookings", "booking-1")
    booking["razorpay_payment_id"] = "pay_1"

    with pytest.raises(refunds.RefundError) as e:
        refunds.refund_booking(booking, reason="oops", amount_paise=9_999_999)

    assert e.value.code == "invalid_amount"
    assert rzp.refund_calls == []


def test_partial_refunds_cannot_exceed_capture_in_aggregate(db, rzp):
    """Two partials that individually pass must not together over-refund."""
    booking = db.get("bookings", "booking-1")
    booking["razorpay_payment_id"] = "pay_1"

    refunds.refund_booking(booking, reason="partial 1", amount_paise=3_000_000)
    booking = db.get("bookings", "booking-1")

    with pytest.raises(refunds.RefundError) as e:
        refunds.refund_booking(booking, reason="partial 2", amount_paise=3_000_000)

    assert e.value.code == "over_refund"
    assert len(rzp.refund_calls) == 1


def test_partial_refund_leaves_booking_paid(db, rzp):
    booking = db.get("bookings", "booking-1")
    booking["razorpay_payment_id"] = "pay_1"

    refunds.refund_booking(booking, reason="goodwill", amount_paise=1_000_000)

    assert db.get("bookings", "booking-1")["payment_status"] == "paid"


def test_provider_failure_marks_refund_failed_not_silent(db, rzp, monkeypatch):
    booking = db.get("bookings", "booking-1")
    booking["razorpay_payment_id"] = "pay_1"

    class Boom:
        @property
        def payment(self):
            raise RuntimeError("razorpay down")

    monkeypatch.setattr(refunds, "client", Boom())

    with pytest.raises(refunds.RefundError) as e:
        refunds.refund_booking(booking, reason="test")

    assert e.value.code == "provider_failed"
    # The intent row survives so reconciliation can see the attempt.
    assert db.rows("refunds")[0]["status"] == "failed"
    assert db.get("bookings", "booking-1")["payment_status"] == "paid"


# ── Payouts ───────────────────────────────────────────────────────────────────

def test_split_sums_to_gross(db, monkeypatch):
    monkeypatch.setattr(payouts, "SELLER_SUCCESS_FEE_RATE", 0.05)
    for gross in (1, 99, 100, 12_345, 5_000_000, 999_999_999):
        net, fee = payouts.compute_split(gross)
        assert net + fee == gross, f"split lost money at {gross}"
        assert net > 0 and fee >= 0


@pytest.fixture
def live_route(monkeypatch):
    """
    Exercise the real Route path.

    SIMULATE_PAYOUTS defaults on, because Route onboarding needs a registered
    business entity this project does not have — without simulation a booking
    could never reach its terminal state. These tests pin the flag off so the
    genuine transfer path stays covered and does not rot while unused.
    """
    monkeypatch.setattr(payouts, "SIMULATE_PAYOUTS", False)


def test_payout_pays_seller_and_writes_ledger(db, rzp, live_route):
    booking = db.get("bookings", "booking-1")
    listing = db.get("listings", "listing-expensive")
    ledger.record_capture("booking-1", BUYER["id"], 5_000_000, "pay_1")

    result = payouts.release_payout(booking, listing)

    assert result["status"] == "paid"
    assert rzp.transfer_calls[0]["account"] == "acc_seller1"
    assert rzp.transfer_calls[0]["amount"] == result["net_paise"]
    assert ledger.booking_balance_paise("booking-1") == 0


def test_seller_cannot_be_paid_twice(db, rzp, live_route):
    booking = db.get("bookings", "booking-1")
    listing = db.get("listings", "listing-expensive")

    payouts.release_payout(booking, listing)
    second = payouts.release_payout(booking, listing)

    assert second["status"] == "already_paid"
    assert len(rzp.transfer_calls) == 1, "a second transfer was actually sent"


def test_payout_blocked_without_linked_account(db, rzp, live_route):
    seller = db.get("users", SELLER["id"])
    seller["razorpay_linked_account_id"] = None

    with pytest.raises(payouts.PayoutError) as e:
        payouts.release_payout(
            db.get("bookings", "booking-1"), db.get("listings", "listing-expensive")
        )

    assert e.value.code == "no_linked_account"
    assert rzp.transfer_calls == []


# ── Simulated payouts (the mode this project actually runs in) ────────────────

def test_simulated_payout_completes_without_a_linked_account(db, rzp):
    """
    With Route unavailable, the payout still settles: the row, the split, the
    ledger entries and the state transition are all real. Only the outbound
    bank leg is stood in for.
    """
    db.get("users", SELLER["id"])["razorpay_linked_account_id"] = None
    ledger.record_capture("booking-1", BUYER["id"], 5_000_000, "pay_1")

    result = payouts.release_payout(
        db.get("bookings", "booking-1"), db.get("listings", "listing-expensive")
    )

    assert result["status"] == "paid"
    assert rzp.transfer_calls == [], "no real transfer may be attempted"
    assert ledger.booking_balance_paise("booking-1") == 0


def test_simulated_transfer_id_is_obviously_not_real(db, rzp):
    """
    Anyone reading the ledger must be able to tell a simulated payout from a
    genuine one at a glance — otherwise the audit trail quietly implies money
    moved when it did not.
    """
    db.get("users", SELLER["id"])["razorpay_linked_account_id"] = None

    result = payouts.release_payout(
        db.get("bookings", "booking-1"), db.get("listings", "listing-expensive")
    )

    assert result["transfer_id"].startswith("sim_")


def test_simulated_payout_is_still_idempotent(db, rzp):
    booking = db.get("bookings", "booking-1")
    listing = db.get("listings", "listing-expensive")

    payouts.release_payout(booking, listing)
    second = payouts.release_payout(booking, listing)

    assert second["status"] == "already_paid"


def test_payout_hold_is_honoured_even_when_simulated(db, rzp):
    """A seller under review must not be paid, real transfer or not."""
    db.get("users", SELLER["id"])["payout_hold"] = True

    with pytest.raises(payouts.PayoutError) as e:
        payouts.release_payout(
            db.get("bookings", "booking-1"), db.get("listings", "listing-expensive")
        )

    assert e.value.code == "on_hold"


def test_payout_blocked_when_seller_on_hold(db, rzp):
    db.get("users", SELLER["id"])["payout_hold"] = True

    with pytest.raises(payouts.PayoutError) as e:
        payouts.release_payout(
            db.get("bookings", "booking-1"), db.get("listings", "listing-expensive")
        )

    assert e.value.code == "on_hold"
    assert rzp.transfer_calls == []


def test_unpaid_booking_cannot_be_paid_out(db, rzp):
    booking = db.get("bookings", "booking-1")
    booking["payment_status"] = "pending"

    with pytest.raises(payouts.PayoutError) as e:
        payouts.release_payout(booking, db.get("listings", "listing-expensive"))

    assert e.value.code == "not_payable"
    assert rzp.transfer_calls == []


# ── Reconciliation ────────────────────────────────────────────────────────────

def test_reconciliation_is_clean_on_a_consistent_booking(db, rzp):
    booking = db.get("bookings", "booking-1")
    listing = db.get("listings", "listing-expensive")
    ledger.record_capture("booking-1", BUYER["id"], to_paise(50000.0), "pay_1")
    payouts.release_payout(booking, listing)

    report = reconcile.find_discrepancies()
    assert report["issue_count"] == 0, report["issues"]


def test_reconciliation_catches_a_missing_capture(db):
    """A booking marked paid whose money was never recorded."""
    report = reconcile.find_discrepancies()

    types = {i["type"] for i in report["issues"]}
    assert "capture_mismatch" in types


def test_reconciliation_catches_negative_balance(db):
    ledger.record_capture("booking-1", BUYER["id"], to_paise(50000.0), "pay_1")
    ledger.record_payout("booking-1", SELLER["id"], 9_000_000, "trf_rogue")

    report = reconcile.find_discrepancies()
    types = {i["type"] for i in report["issues"]}
    assert "negative_balance" in types


def test_reconciliation_flags_stuck_pending_bookings(db):
    db.rows("bookings").append(
        make_booking("booking-stuck", order_id="order_stuck", payment_status="pending")
    )

    report = reconcile.find_discrepancies()
    stuck = [i for i in report["issues"] if i["type"] == "stuck_pending"]
    assert any(i["booking_id"] == "booking-stuck" for i in stuck)
