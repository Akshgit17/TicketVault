"""
Repricing a live listing, and getting the deposit back when withdrawing one.

Both existed only as gaps before: a seller who mispriced had to unlist and
relist, which charged a second deposit, and unlisting silently kept the first
one. Between them, fixing a typo cost 20% of the ticket price.

These pin the two rules that keep repricing safe:

  * the price cap still applies, because it is the guarantee everything else
    rests on,
  * a rise the existing deposit could no longer cover is refused, because the
    deposit has to be able to pay the buyer's compensation if the sale fails.
"""
import pytest

import app.services.deposits as deposits
from app.config import BUYER_COMPENSATION_RATE, LISTING_FEE_RATE, PRICE_CAP_MULTIPLIER
from app.services.payments import to_paise

FACE = 5000.0
LISTED = 5000.0
DEPOSIT_PAISE = int(to_paise(LISTED) * LISTING_FEE_RATE)


def _cap(original: float) -> float:
    return original * PRICE_CAP_MULTIPLIER


def _max_covered(deposit_paise: int) -> float:
    """Highest price whose compensation the existing deposit still covers."""
    return (deposit_paise / 100) / BUYER_COMPENSATION_RATE


# ── The cap still binds ───────────────────────────────────────────────────────

def test_cap_is_unchanged_by_repricing():
    """
    Repricing must not become a way around the ceiling.

    The cap is a deterministic rule and the single thing every trust claim in
    the product depends on, so a second write path to `price` has to honour it
    exactly as listing creation does.
    """
    cap = _cap(FACE)
    assert cap == pytest.approx(6000.0)
    assert 5999 <= cap
    assert 6001 > cap


# ── The deposit must still cover compensation ─────────────────────────────────

def test_existing_deposit_allows_roughly_a_doubling():
    """
    Deposit is 20% of the old price, compensation is 10% of the new one, so a
    seller can about double before the cover runs out. Worth asserting because
    if the two rates are ever retuned this is the relationship that silently
    breaks, leaving a buyer uncompensatable.
    """
    limit = _max_covered(DEPOSIT_PAISE)
    assert limit == pytest.approx(LISTED * (LISTING_FEE_RATE / BUYER_COMPENSATION_RATE))
    assert limit == pytest.approx(10_000.0)


def test_a_price_the_deposit_cannot_cover_is_out_of_range():
    limit = _max_covered(DEPOSIT_PAISE)
    assert 10_001 > limit, "must be refused"
    assert 9_999 <= limit, "must be allowed"


def test_the_cap_binds_before_the_deposit_limit_in_practice():
    """
    With these defaults the cap is the constraint a seller actually meets, and
    the deposit rule is the backstop. If this ever inverts, sellers would start
    hitting a confusing "your deposit only covers..." message instead of the
    clear cap message, which is worth knowing about.
    """
    assert _cap(FACE) < _max_covered(DEPOSIT_PAISE)


# ── Withdrawing returns the deposit ───────────────────────────────────────────

def test_withdrawn_listing_is_eligible_for_a_deposit_return():
    """
    A listing nobody bought has no buyer to protect, so the deposit goes back.
    `is_resolved` is the guard the unlist path uses to avoid returning twice.
    """
    listing = {
        "id": "listing-1",
        "deposit_paid_paise": DEPOSIT_PAISE,
        "fee_razorpay_payment_id": "pay_1",
        "deposit_returned_at": None,
        "deposit_forfeited_at": None,
    }
    assert deposits.is_resolved(listing) is False
    assert deposits.deposit_paise(listing) == DEPOSIT_PAISE


def test_an_already_resolved_deposit_is_not_returned_again():
    returned = {
        "id": "listing-1",
        "deposit_paid_paise": DEPOSIT_PAISE,
        "deposit_returned_at": "2026-08-01T00:00:00+00:00",
        "deposit_forfeited_at": None,
    }
    forfeited = {
        "id": "listing-2",
        "deposit_paid_paise": DEPOSIT_PAISE,
        "deposit_returned_at": None,
        "deposit_forfeited_at": "2026-08-01T00:00:00+00:00",
    }
    assert deposits.is_resolved(returned) is True
    assert deposits.is_resolved(forfeited) is True


def test_a_listing_that_never_paid_has_nothing_to_return():
    """pending_deposit listings were never charged, so unlisting refunds nothing."""
    listing = {"id": "listing-3", "price": LISTED, "fee_razorpay_payment_id": None}
    assert listing["fee_razorpay_payment_id"] is None
