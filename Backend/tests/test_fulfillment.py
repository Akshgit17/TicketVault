"""
Phase 3 — transfer-based fulfilment.

The behaviours that matter most here are the ones the old design got wrong:
  - a listing whose checkout was abandoned must return to the market
  - a seller who never transfers must auto-refund the buyer
  - escrow must not release until after the event
  - a dispute must stay open until then
"""
from datetime import datetime, timedelta, timezone

import pytest

import app.jobs.fulfillment_jobs as jobs
import app.services.fulfillment as f
import app.services.payouts as payouts
import app.services.refunds as refunds
from tests.conftest import BUYER, SELLER, make_booking, make_listing, patch_supabase
from tests.fake_supabase import FakeSupabase

UTC = timezone.utc


def ts(**delta) -> str:
    return (datetime.now(UTC) + timedelta(**delta)).isoformat()


def make_event(event_id="event-1", transfer_supported=True, days_out=10, window=None):
    return {
        "id": event_id,
        "title": "Test Show",
        "city_id": "city-1",
        "date": ts(days=days_out),
        "transfer_supported": transfer_supported,
        "transfer_window_opens_at": window,
    }


@pytest.fixture
def db(monkeypatch):
    fake = FakeSupabase({
        "users": [
            dict(BUYER),
            {**SELLER, "razorpay_linked_account_id": "acc_1", "payout_hold": False},
        ],
        "events": [make_event()],
        "listings": [make_listing(status="sold")],
        "bookings": [make_booking(payment_status="paid")],
        "booking_events": [],
        "ledger_entries": [],
        "payouts": [],
        "refunds": [],
    })
    fake.unique["ledger_entries"] = ["idempotency_key"]
    fake.unique["payouts"] = ["booking_id"]
    patch_supabase(monkeypatch, fake)
    return fake


# ── State machine ─────────────────────────────────────────────────────────────

def test_valid_path_runs_end_to_end(db):
    booking = db.get("bookings", "booking-1")

    f.begin_fulfillment(booking, make_event())
    assert db.get("bookings", "booking-1")["fulfillment_status"] == f.AWAITING_TRANSFER

    f.mark_transfer_initiated(db.get("bookings", "booking-1"), SELLER["id"])
    assert db.get("bookings", "booking-1")["fulfillment_status"] == f.TRANSFER_INITIATED

    f.confirm_transfer_received(db.get("bookings", "booking-1"), BUYER["id"])
    assert db.get("bookings", "booking-1")["fulfillment_status"] == f.TRANSFER_CONFIRMED

    f.mark_released(db.get("bookings", "booking-1"))
    assert db.get("bookings", "booking-1")["fulfillment_status"] == f.RELEASED


@pytest.mark.parametrize(
    "start,target",
    [
        (f.NOT_STARTED, f.TRANSFER_CONFIRMED),   # skip the whole flow
        (f.AWAITING_TRANSFER, f.RELEASED),       # pay out without confirmation
        (f.RELEASED, f.FAILED),                  # reopen a terminal booking
        (f.FAILED, f.AWAITING_TRANSFER),
        (f.TRANSFER_CONFIRMED, f.TRANSFER_INITIATED),  # go backwards
    ],
)
def test_invalid_transitions_are_refused(db, start, target):
    booking = db.get("bookings", "booking-1")
    booking["fulfillment_status"] = start

    with pytest.raises(f.FulfillmentError) as e:
        f.transition(booking, target, actor="system")

    assert e.value.code == "invalid_transition"
    assert db.get("bookings", "booking-1")["fulfillment_status"] == start


def test_concurrent_transitions_only_one_wins(db):
    """Both callers read the same state; the second must be rejected, not lost."""
    booking = db.get("bookings", "booking-1")
    f.begin_fulfillment(booking, make_event())

    stale = dict(db.get("bookings", "booking-1"))
    f.mark_transfer_initiated(stale, SELLER["id"])

    with pytest.raises(f.FulfillmentError) as e:
        f.mark_transfer_initiated(stale, SELLER["id"])
    assert e.value.code == "conflict"


def test_every_transition_is_audited(db):
    booking = db.get("bookings", "booking-1")
    f.begin_fulfillment(booking, make_event())
    f.mark_transfer_initiated(db.get("bookings", "booking-1"), SELLER["id"])

    events = db.rows("booking_events")
    assert [e["to_status"] for e in events] == [f.AWAITING_TRANSFER, f.TRANSFER_INITIATED]
    assert events[1]["actor"] == "seller"
    assert events[1]["actor_id"] == SELLER["id"]


def test_non_transfer_events_stay_on_legacy_flow(db):
    booking = db.get("bookings", "booking-1")
    f.begin_fulfillment(booking, make_event(transfer_supported=False))

    assert db.get("bookings", "booking-1")["fulfillment_status"] == f.NOT_STARTED


def test_unknown_transfer_support_is_treated_as_unsupported(db):
    """transfer_supported is NULL until Phase 0.1 validation fills it in."""
    booking = db.get("bookings", "booking-1")
    f.begin_fulfillment(booking, {**make_event(), "transfer_supported": None})

    assert db.get("bookings", "booking-1")["fulfillment_status"] == f.NOT_STARTED


# ── Deadlines ─────────────────────────────────────────────────────────────────

def test_sla_starts_when_the_transfer_window_opens(db):
    """
    BMS enables transfer per event, often near the date. A seller cannot be
    penalised for missing a deadline that elapsed before they could act.
    """
    window = ts(days=5)
    f.begin_fulfillment(db.get("bookings", "booking-1"), make_event(window=window))

    deadline = datetime.fromisoformat(db.get("bookings", "booking-1")["transfer_deadline"])
    assert deadline > datetime.fromisoformat(window)


def test_no_release_clock_until_the_buyer_confirms(db):
    """
    Starting fulfilment must NOT schedule a release.

    The clock runs from confirmation, so setting it here would let escrow
    release for a ticket the buyer never said they received.
    """
    f.begin_fulfillment(db.get("bookings", "booking-1"), make_event(days_out=10))

    assert db.get("bookings", "booking-1")["escrow_release_at"] is None


def test_escrow_release_runs_from_confirmation_not_the_event(db, monkeypatch):
    """
    Release is buyer-confirmation + SETTLEMENT_HOLD_HOURS.

    It used to be event date + 24h, a rule inherited from the QR model where a
    screenshot could only be validated at the gate. Under the transfer model
    the issuer has already put the ticket in the buyer's account, so waiting
    weeks past confirmation punishes honest sellers and buys nothing — and it
    made the full lifecycle impossible to demonstrate for an event a month out.
    """
    monkeypatch.setattr(f, "SETTLEMENT_HOLD_HOURS", 6)

    event = make_event(days_out=30)
    f.begin_fulfillment(db.get("bookings", "booking-1"), event)
    f.mark_transfer_initiated(db.get("bookings", "booking-1"), SELLER["id"], None)

    before = datetime.now(timezone.utc)
    f.confirm_transfer_received(db.get("bookings", "booking-1"), BUYER["id"])

    release = datetime.fromisoformat(db.get("bookings", "booking-1")["escrow_release_at"])
    event_date = datetime.fromisoformat(event["date"])

    assert release < event_date, "must not wait for the event"
    assert timedelta(hours=5) < (release - before) < timedelta(hours=7)


def test_settlement_hold_can_be_shortened_for_a_demo(db, monkeypatch):
    """The hold is config-driven so a demo can complete without editing code."""
    monkeypatch.setattr(f, "SETTLEMENT_HOLD_HOURS", 0)

    f.begin_fulfillment(db.get("bookings", "booking-1"), make_event(days_out=30))
    f.mark_transfer_initiated(db.get("bookings", "booking-1"), SELLER["id"], None)
    f.confirm_transfer_received(db.get("bookings", "booking-1"), BUYER["id"])

    release = datetime.fromisoformat(db.get("bookings", "booking-1")["escrow_release_at"])
    assert release <= datetime.now(timezone.utc) + timedelta(seconds=5)


def test_disputes_stay_open_until_terminal(db):
    booking = db.get("bookings", "booking-1")
    for status in (f.NOT_STARTED, f.AWAITING_TRANSFER, f.TRANSFER_INITIATED, f.TRANSFER_CONFIRMED):
        assert f.can_dispute({**booking, "fulfillment_status": status}) is True
    for status in (f.RELEASED, f.FAILED):
        assert f.can_dispute({**booking, "fulfillment_status": status}) is False


# ── Jobs ──────────────────────────────────────────────────────────────────────

def test_expired_reservations_return_to_the_market(db):
    """The original bug: lock_expiry was written but never read."""
    db.rows("listings").append({
        **make_listing("listing-stale", status="locked"),
        "locked_by": BUYER["id"], "lock_expiry": ts(minutes=-30),
    })

    result = jobs.release_expired_reservations()

    assert "listing-stale" in result["released"]
    stale = db.get("listings", "listing-stale")
    assert stale["status"] == "active"
    assert stale["locked_by"] is None


def test_unexpired_reservations_are_left_alone(db):
    db.rows("listings").append({
        **make_listing("listing-fresh", status="locked"),
        "locked_by": BUYER["id"], "lock_expiry": ts(minutes=+10),
    })

    jobs.release_expired_reservations()
    assert db.get("listings", "listing-fresh")["status"] == "locked"


def test_breached_transfer_refunds_buyer_and_requires_new_deposit(db, monkeypatch):
    refunded = []
    monkeypatch.setattr(
        refunds, "refund_booking",
        lambda booking, reason, amount_paise=None: refunded.append(booking["id"]),
    )

    booking = db.get("bookings", "booking-1")
    booking.update({
        "fulfillment_status": f.AWAITING_TRANSFER,
        "transfer_deadline": ts(hours=-1),
        "razorpay_payment_id": "pay_1",
    })

    result = jobs.fail_breached_transfers()

    assert result["refunded"] == ["booking-1"]
    assert refunded == ["booking-1"]
    assert db.get("bookings", "booking-1")["fulfillment_status"] == f.FAILED

    # The listing needs a NEW deposit before it can sell again.
    #
    # Not `active` (a forfeited deposit backs nobody, so the next buyer would
    # be refunded but never compensated) and not `cancelled` (the SLA runs
    # overnight and nothing notifies the seller, so a single miss is not proof
    # of bad faith). pending_fee keeps the listing but gates it behind money
    # genuinely at risk.
    assert db.get("listings", "listing-expensive")["status"] == "pending_fee"


def test_disputed_booking_is_not_paid_out(db, monkeypatch):
    """
    A dispute must freeze the payout.

    Without this the settlement hold is theatre: the buyer confirms, spots a
    problem inside the window, reports it, and the release job pays the seller
    anyway because it only looked at fulfilment status. Freezing money is
    reversible; paying it out is not.
    """
    paid_out = []
    monkeypatch.setattr(
        payouts, "release_payout",
        lambda booking, listing: paid_out.append(booking["id"]),
    )

    booking = db.get("bookings", "booking-1")
    booking.update({
        "fulfillment_status":  f.TRANSFER_CONFIRMED,
        "confirmation_status": "disputed",
        "escrow_release_at":   ts(hours=-1),
    })

    result = jobs.release_due_escrow()

    assert result["released"] == []
    assert paid_out == [], "a disputed booking must not pay the seller"
    assert db.get("bookings", "booking-1")["fulfillment_status"] == f.TRANSFER_CONFIRMED


def test_undisputed_booking_still_pays_out(db, monkeypatch):
    """The dispute filter must not accidentally freeze every booking."""
    paid_out = []
    monkeypatch.setattr(
        payouts, "release_payout",
        lambda booking, listing: paid_out.append(booking["id"]),
    )

    booking = db.get("bookings", "booking-1")
    booking.update({
        "fulfillment_status":  f.TRANSFER_CONFIRMED,
        "confirmation_status": "pending",
        "escrow_release_at":   ts(hours=-1),
    })

    jobs.release_due_escrow()

    assert paid_out == ["booking-1"]


def test_transfer_within_deadline_is_not_refunded(db, monkeypatch):
    monkeypatch.setattr(
        refunds, "refund_booking",
        lambda *a, **k: pytest.fail("refunded a booking that was still in time"),
    )

    db.get("bookings", "booking-1").update({
        "fulfillment_status": f.AWAITING_TRANSFER,
        "transfer_deadline": ts(hours=+2),
    })

    assert jobs.fail_breached_transfers()["refunded"] == []


def test_escrow_releases_only_when_due(db, monkeypatch):
    paid = []
    monkeypatch.setattr(
        payouts, "release_payout",
        lambda booking, listing: paid.append(booking["id"]) or {"status": "paid"},
    )

    db.get("bookings", "booking-1").update({
        "fulfillment_status": f.TRANSFER_CONFIRMED,
        "escrow_release_at": ts(hours=+5),      # not yet
    })
    assert jobs.release_due_escrow()["released"] == []
    assert paid == []

    db.get("bookings", "booking-1")["escrow_release_at"] = ts(hours=-1)
    assert jobs.release_due_escrow()["released"] == ["booking-1"]
    assert paid == ["booking-1"]
    assert db.get("bookings", "booking-1")["fulfillment_status"] == f.RELEASED


def test_failed_payout_leaves_booking_retryable(db, monkeypatch):
    """A seller who has not finished onboarding should resolve on a later run."""
    def boom(booking, listing):
        raise RuntimeError("no linked account")

    monkeypatch.setattr(payouts, "release_payout", boom)

    db.get("bookings", "booking-1").update({
        "fulfillment_status": f.TRANSFER_CONFIRMED,
        "escrow_release_at": ts(hours=-1),
    })

    result = jobs.release_due_escrow()

    assert result["released"] == []
    assert len(result["failures"]) == 1
    # Still confirmed, so the next run picks it up again.
    assert db.get("bookings", "booking-1")["fulfillment_status"] == f.TRANSFER_CONFIRMED


def test_jobs_are_idempotent_when_run_twice(db, monkeypatch):
    monkeypatch.setattr(refunds, "refund_booking", lambda *a, **k: None)
    monkeypatch.setattr(payouts, "release_payout", lambda *a, **k: {"status": "paid"})

    db.rows("listings").append({
        **make_listing("listing-stale", status="locked"),
        "lock_expiry": ts(minutes=-30),
    })

    first = jobs.run_all()
    second = jobs.run_all()

    assert first["reservations"]["count"] == 1
    assert second["reservations"]["count"] == 0
    assert second["breached"]["refunded"] == []
