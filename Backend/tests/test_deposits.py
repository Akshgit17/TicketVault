"""
The seller's security deposit.

The deposit is the mechanism that makes the buyer guarantee funded rather than
promised, so the properties that matter are:

  * it comes back in full when the seller delivers,
  * it is kept, and partly paid to the buyer, when the seller does not,
  * exactly one of those happens, no matter how many times a job retries.

The invariant underneath all of it: a resolved listing's deposit entries net to
zero, whichever ending occurred.
"""
import pytest

import app.jobs.fulfillment_jobs as jobs
import app.services.deposits as deposits
import app.services.ledger as ledger
import app.services.refunds as refunds
from app.config import BUYER_COMPENSATION_RATE, LISTING_FEE_RATE
from app.services.payments import to_paise
from tests.conftest import BUYER, SELLER, make_booking, make_listing, patch_supabase
from tests.fake_supabase import FakeSupabase

PRICE = 50_000.0
DEPOSIT_PAISE = int(to_paise(PRICE) * LISTING_FEE_RATE)


class FakeRazorpay:
    """Records refund calls so tests can assert the deposit was really returned."""

    def __init__(self, fail=False):
        self.refund_calls = []
        self.fail = fail

    class _Payment:
        def __init__(self, outer):
            self.outer = outer

        def refund(self, payment_id, params):
            if self.outer.fail:
                raise RuntimeError("gateway down")
            self.outer.refund_calls.append((payment_id, params))
            return {"id": f"rfnd_{len(self.outer.refund_calls)}", "status": "processed"}

    @property
    def payment(self):
        return self._Payment(self)


def _listing(**overrides):
    base = make_listing(status="sold")
    base.update({
        "fee_razorpay_payment_id": "pay_deposit_1",
        "deposit_paid_paise":      DEPOSIT_PAISE,
        "deposit_returned_at":     None,
        "deposit_refund_id":       None,
        "deposit_forfeited_at":    None,
        "deposit_forfeit_reason":  None,
    })
    base.update(overrides)
    return base


@pytest.fixture
def db(monkeypatch):
    fake = FakeSupabase({
        "users":    [dict(BUYER), dict(SELLER)],
        "listings": [_listing()],
        "bookings": [make_booking(payment_status="paid", total_price=PRICE)],
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
    monkeypatch.setattr(deposits, "client", fake)
    monkeypatch.setattr(refunds, "client", fake)
    return fake


# ── Return ────────────────────────────────────────────────────────────────────

def test_deposit_is_returned_in_full(db, rzp):
    result = deposits.return_deposit(_listing())

    assert result["status"] == "returned"
    assert result["amount_paise"] == DEPOSIT_PAISE

    # A real refund against the deposit's own payment, not the booking's.
    assert len(rzp.refund_calls) == 1
    payment_id, params = rzp.refund_calls[0]
    assert payment_id == "pay_deposit_1"
    assert params["amount"] == DEPOSIT_PAISE

    kinds = [e["kind"] for e in db.rows("ledger_entries")]
    assert ledger.KIND_DEPOSIT_RETURN in kinds


def test_returning_twice_refunds_only_once(db, rzp):
    deposits.return_deposit(_listing())
    stored = db.rows("listings")[0]

    again = deposits.return_deposit(stored)

    assert again["status"] == "already_returned"
    assert len(rzp.refund_calls) == 1, "a retried job must not refund the deposit twice"


def test_return_is_refused_after_forfeit(db, rzp):
    forfeited = _listing(deposit_forfeited_at="2026-08-01T00:00:00+00:00")

    with pytest.raises(deposits.DepositError) as exc:
        deposits.return_deposit(forfeited)

    assert exc.value.code == "already_forfeited"
    assert rzp.refund_calls == []


def test_gateway_failure_leaves_deposit_unreturned(db, monkeypatch):
    """A failed refund must not mark the deposit returned — the next run retries."""
    monkeypatch.setattr(deposits, "client", FakeRazorpay(fail=True))

    with pytest.raises(deposits.DepositError) as exc:
        deposits.return_deposit(_listing())

    assert exc.value.code == "provider_failed"
    assert db.rows("listings")[0]["deposit_returned_at"] is None


# ── Forfeit ───────────────────────────────────────────────────────────────────

def test_forfeit_splits_between_buyer_and_platform(db):
    booking = make_booking(payment_status="paid", total_price=PRICE)

    result = deposits.forfeit_deposit(_listing(), booking, reason="seller_did_not_transfer")

    expected_compensation = int(round(to_paise(PRICE) * BUYER_COMPENSATION_RATE))
    assert result["status"] == "forfeited"
    assert result["compensation_paise"] == expected_compensation
    assert result["retained_paise"] == DEPOSIT_PAISE - expected_compensation
    # The whole deposit is accounted for; nothing evaporates.
    assert result["compensation_paise"] + result["retained_paise"] == DEPOSIT_PAISE

    kinds = {e["kind"] for e in db.rows("ledger_entries")}
    assert ledger.KIND_COMPENSATION in kinds
    assert ledger.KIND_FORFEIT in kinds


def test_forfeit_is_idempotent(db):
    booking = make_booking(payment_status="paid", total_price=PRICE)

    deposits.forfeit_deposit(_listing(), booking, reason="x")
    again = deposits.forfeit_deposit(db.rows("listings")[0], booking, reason="x")

    assert again["status"] == "already_forfeited"
    compensations = [
        e for e in db.rows("ledger_entries") if e["kind"] == ledger.KIND_COMPENSATION
    ]
    assert len(compensations) == 1, "the buyer must not be compensated twice"


def test_the_split_always_sums_to_the_deposit(db, monkeypatch):
    """
    Whatever the share is set to, the two parts must add up to exactly the
    deposit. `retained` is taken as a share and `compensation` is the
    remainder, so a rounding remainder can never go missing.

    This replaced a test asserting that compensation gets clamped when it would
    exceed the deposit. Splitting the deposit rather than deriving the buyer's
    share from the ticket price made overshoot impossible, so the clamp had
    nothing left to guard.
    """
    booking = make_booking(payment_status="paid", total_price=PRICE)

    for share in (0.0, 0.5, 0.9, 1.0):
        monkeypatch.setattr(deposits, "PLATFORM_FORFEIT_SHARE", share)
        db.tables["listings"] = [_listing()]
        db.tables["ledger_entries"] = []

        result = deposits.forfeit_deposit(_listing(), booking, reason="x")

        assert result["compensation_paise"] + result["retained_paise"] == DEPOSIT_PAISE
        assert 0 <= result["compensation_paise"] <= DEPOSIT_PAISE
        assert 0 <= result["retained_paise"] <= DEPOSIT_PAISE


def test_platform_and_buyer_split_the_deposit_evenly(db):
    """The configured 50/50. Stated explicitly so a retune is a visible change."""
    booking = make_booking(payment_status="paid", total_price=PRICE)

    result = deposits.forfeit_deposit(_listing(), booking, reason="x")

    assert result["retained_paise"] == DEPOSIT_PAISE // 2
    assert result["compensation_paise"] == DEPOSIT_PAISE - DEPOSIT_PAISE // 2


# ── The invariant ─────────────────────────────────────────────────────────────

def test_returned_deposit_nets_to_zero(db, rzp):
    listing = _listing()
    deposits.record_deposit_paid(listing, "pay_deposit_1")
    deposits.return_deposit(db.rows("listings")[0])

    assert ledger.deposit_balance_paise(listing["id"]) == 0


def test_forfeited_deposit_nets_to_zero(db):
    listing = _listing()
    booking = make_booking(payment_status="paid", total_price=PRICE)

    deposits.record_deposit_paid(listing, "pay_deposit_1")
    deposits.forfeit_deposit(db.rows("listings")[0], booking, reason="x")

    assert ledger.deposit_balance_paise(listing["id"]) == 0


# ── Wired into the jobs ───────────────────────────────────────────────────────

def test_sla_breach_refunds_buyer_and_forfeits_deposit(db, rzp, monkeypatch):
    """The unhappy path, end to end: buyer made whole, seller's deposit kept."""
    breached = make_booking(payment_status="paid", total_price=PRICE)
    breached["fulfillment_status"] = "awaiting_transfer"
    breached["transfer_deadline"] = "2020-01-01T00:00:00+00:00"
    breached["razorpay_payment_id"] = "pay_booking_1"
    db.tables["bookings"] = [breached]
    db.tables["listings"] = [_listing()]

    result = jobs.fail_breached_transfers()

    assert result["refunded"] == [breached["id"]]
    assert result["failures"] == []

    listing = db.rows("listings")[0]
    assert listing["deposit_returned_at"] is None, "a forfeited deposit is never returned"

    # The forfeiture is asserted against the LEDGER, not the listing flag.
    # `_require_new_deposit` deliberately clears the listing's deposit state so
    # the seller can relist with fresh money at risk, which means the flag is
    # transient. The ledger is append-only, so it is the durable record of what
    # actually happened.
    kinds = {e["kind"] for e in db.rows("ledger_entries")}
    assert ledger.KIND_REFUND in kinds, "buyer gets the ticket price back"
    assert ledger.KIND_COMPENSATION in kinds, "buyer gets compensated on top"
    assert ledger.KIND_FORFEIT in kinds, "the platform retains the remainder"


def test_failed_listing_requires_a_new_deposit_before_reselling(db, rzp):
    """
    A listing whose deposit was forfeited must not go straight back on sale,
    but must not be destroyed either.

    Not `active`: forfeiture is one-way, so the ticket would be backed by
    nothing and the next buyer would be refunded but never compensated.

    Not `cancelled`: the SLA runs overnight and nothing notifies the seller, so
    one miss is not proof of bad faith.

    `pending_fee` keeps the listing and its details intact while gating the
    market behind a fresh deposit that is genuinely at risk.
    """
    breached = make_booking(payment_status="paid", total_price=PRICE)
    breached["fulfillment_status"] = "awaiting_transfer"
    breached["transfer_deadline"] = "2020-01-01T00:00:00+00:00"
    breached["razorpay_payment_id"] = "pay_booking_1"
    db.tables["bookings"] = [breached]
    db.tables["listings"] = [_listing(status="sold")]

    jobs.fail_breached_transfers()

    listing = db.rows("listings")[0]
    assert listing["status"] == "pending_fee"
    assert listing["status"] != "active", "must not resell unbacked"


def test_relisting_clears_deposit_state_so_a_new_one_can_be_taken(db, rzp):
    """
    The seller gets a genuine second chance, backed by new money.

    If the forfeiture flags survived, the next buyer could not be compensated
    because forfeit_deposit() refuses to forfeit twice. Clearing them is what
    makes the second cycle real rather than cosmetic. The ledger keeps the
    original forfeit entry, so history is not rewritten.
    """
    breached = make_booking(payment_status="paid", total_price=PRICE)
    breached["fulfillment_status"] = "awaiting_transfer"
    breached["transfer_deadline"] = "2020-01-01T00:00:00+00:00"
    breached["razorpay_payment_id"] = "pay_booking_1"
    db.tables["bookings"] = [breached]
    db.tables["listings"] = [_listing(status="sold")]

    jobs.fail_breached_transfers()
    listing = db.rows("listings")[0]

    assert listing["deposit_forfeited_at"] is None, "a new deposit must be forfeitable"
    assert listing["deposit_paid_paise"] is None

    # The forfeit is still on the permanent record.
    forfeits = [e for e in db.rows("ledger_entries") if e["kind"] == ledger.KIND_FORFEIT]
    assert len(forfeits) == 1


def test_seller_can_relist_and_the_new_deposit_is_at_risk_too(db, rzp):
    """
    The whole point of pending_deposit rather than cancelled: the seller gets a
    real second chance, and the second buyer is backed just as well as the first.

    Walks two full cycles. If the second forfeit ever stops firing, a seller
    could burn one deposit and then fail indefinitely at no cost, which is the
    exact hole this design closes.
    """
    first_buyer = make_booking(booking_id="booking-1", payment_status="paid", total_price=PRICE)
    first_buyer["fulfillment_status"] = "awaiting_transfer"
    first_buyer["transfer_deadline"] = "2020-01-01T00:00:00+00:00"
    first_buyer["razorpay_payment_id"] = "pay_1"
    db.tables["bookings"] = [first_buyer]
    db.tables["listings"] = [_listing(status="sold")]

    # Cycle one: seller misses the deadline.
    jobs.fail_breached_transfers()
    listing = db.rows("listings")[0]
    assert listing["status"] == "pending_fee"

    # Seller pays again. This is what /listings/{id}/verify-fee does on success.
    listing["status"] = "active"
    listing["fee_razorpay_payment_id"] = "pay_deposit_2"
    deposits.record_deposit_paid(listing, "pay_deposit_2")

    reloaded = db.rows("listings")[0]
    assert reloaded["deposit_paid_paise"] == DEPOSIT_PAISE, "new money is on the line"

    # Cycle two: a different buyer, and the seller misses again.
    second_buyer = make_booking(booking_id="booking-2", payment_status="paid", total_price=PRICE)
    second_buyer["fulfillment_status"] = "awaiting_transfer"
    second_buyer["transfer_deadline"] = "2020-01-01T00:00:00+00:00"
    second_buyer["razorpay_payment_id"] = "pay_2"
    db.tables["bookings"] = [second_buyer]
    db.rows("listings")[0]["status"] = "sold"

    jobs.fail_breached_transfers()

    # Both buyers were compensated, from two separate deposits.
    comps = [e for e in db.rows("ledger_entries") if e["kind"] == ledger.KIND_COMPENSATION]
    assert len(comps) == 2, "the second buyer must be backed as well as the first"

    forfeits = [e for e in db.rows("ledger_entries") if e["kind"] == ledger.KIND_FORFEIT]
    assert len(forfeits) == 2, "failing twice must cost the seller twice"


def test_a_second_failure_cannot_re_forfeit_the_same_deposit(db):
    """
    The invariant that makes withdrawal necessary.

    If this ever starts passing money to a second buyer, the deposit is being
    spent twice and the ledger no longer nets to zero.
    """
    listing = _listing()
    first_buyer = make_booking(booking_id="booking-1", payment_status="paid", total_price=PRICE)
    second_buyer = make_booking(booking_id="booking-2", payment_status="paid", total_price=PRICE)

    deposits.forfeit_deposit(listing, first_buyer, reason="x")
    again = deposits.forfeit_deposit(db.rows("listings")[0], second_buyer, reason="x")

    assert again["status"] == "already_forfeited"
    compensations = [
        e for e in db.rows("ledger_entries") if e["kind"] == ledger.KIND_COMPENSATION
    ]
    assert len(compensations) == 1, "only the first buyer can be paid from one deposit"
