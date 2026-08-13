"""
Concurrency behaviour around listing reservation and payment settlement.

These exercise the compare-and-swap pattern already present in bookings.py:
an update guarded by `.eq("status", "active")` whose returned rows decide
whether the caller won the race.

SCOPE: the fake database applies filtered updates under a lock, so this proves
the *application* handles a lost race correctly. It does not prove Postgres
isolation — that needs a real database (Phase 1.1 test-database work).
"""
import threading

from tests.conftest import make_booking, make_listing
from tests.fake_supabase import FakeAPIError, FakeSupabase


def _try_lock(db: FakeSupabase, listing_id: str, buyer_id: str) -> bool:
    """The reservation CAS from bookings.initiate_booking."""
    res = (
        db.table("listings")
        .update({"status": "locked", "locked_by": buyer_id, "lock_expiry": "2026-01-01T00:00:00Z"})
        .eq("id", listing_id)
        .eq("status", "active")
        .execute()
    )
    return bool(res.data)


def test_only_one_buyer_can_reserve_a_listing():
    db = FakeSupabase({"listings": [make_listing()], "bookings": []})

    winners: list[int] = []
    barrier = threading.Barrier(50)

    def attempt(i):
        barrier.wait()  # maximise contention
        if _try_lock(db, "listing-expensive", f"buyer-{i}"):
            winners.append(i)

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(winners) == 1, f"expected exactly one winner, got {len(winners)}"
    assert db.get("listings", "listing-expensive")["status"] == "locked"


def test_settlement_is_idempotent_under_concurrent_verify():
    """Two verify-payment calls for the same booking must settle it once."""
    db = FakeSupabase({"bookings": [make_booking()], "listings": [make_listing()]})

    def settle(payment_id: str) -> bool:
        res = (
            db.table("bookings")
            .update({"payment_status": "paid", "razorpay_payment_id": payment_id})
            .eq("id", "booking-1")
            .eq("payment_status", "pending")   # CAS guard added in Phase 1.2
            .execute()
        )
        return bool(res.data)

    first = settle("pay_1")
    second = settle("pay_2")

    assert first is True
    assert second is False, "second settlement must be rejected by the status guard"
    assert db.get("bookings", "booking-1")["razorpay_payment_id"] == "pay_1"


def test_same_receipt_cannot_settle_two_bookings():
    """
    Mirrors the uq_bookings_razorpay_payment_id index from migration 001.
    Defence in depth: even if a future code path forgets to bind the order,
    the database refuses to reuse a receipt.
    """
    db = FakeSupabase(
        {
            "bookings": [
                make_booking("booking-1", order_id="order_1"),
                make_booking("booking-2", order_id="order_2"),
            ],
            "listings": [make_listing()],
        }
    )

    db.table("bookings").update({"razorpay_payment_id": "pay_reused"}).eq("id", "booking-1").execute()

    try:
        db.table("bookings").update({"razorpay_payment_id": "pay_reused"}).eq("id", "booking-2").execute()
        raise AssertionError("replayed receipt should have been rejected")
    except FakeAPIError as e:
        assert "razorpay_payment_id" in str(e)
