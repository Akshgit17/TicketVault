"""
A concert that has started, or been cancelled, must not be sellable or buyable.

Hiding a row from a list is NOT the same as preventing an action on it. The
browse endpoints filtered past events from day one, but the two write paths did
not check at all, so a stale tab, a bookmark, or a link shared an hour earlier
reached them directly. A listing created for a finished show can only ever end
in a refund; a purchase taken for one is money accepted for something that
cannot be delivered.

These assert the rule lives where the row is written, not only where rows are
read.
"""
from datetime import datetime, timedelta, timezone

import pytest

UTC = timezone.utc


def _iso(**delta) -> str:
    return (datetime.now(UTC) + timedelta(**delta)).isoformat()


def _parse(value):
    from app.routes.bookings import _parse_event_date
    return _parse_event_date(value)


# ── The date comparison itself ────────────────────────────────────────────────

def test_a_started_concert_is_in_the_past():
    """
    The boundary is the START TIME, not the end of the day. A gig at 19:00 is
    unsellable at 19:01, because nothing can be transferred once the doors have
    closed.
    """
    now = datetime.now(UTC)

    just_started = _parse(_iso(minutes=-1))
    about_to_start = _parse(_iso(minutes=+1))

    assert just_started <= now, "a concert that began a minute ago is past"
    assert about_to_start > now, "a concert starting in a minute is still sellable"


def test_timestamps_without_a_zone_are_treated_as_utc():
    """
    Postgres can hand back a naive string. Comparing naive to aware raises, and
    the comparison sits directly in front of a payment, so it must not throw.
    """
    naive = _parse("2030-01-01T19:00:00")
    assert naive is not None
    assert naive.tzinfo is not None
    assert naive > datetime.now(UTC)


def test_a_malformed_date_does_not_crash_the_purchase_path():
    """
    Returns None rather than raising, so a bad row degrades to "no date check"
    instead of taking the checkout down.
    """
    assert _parse("not a date") is None
    assert _parse(None) is None
    assert _parse("") is None


# ── The guards exist on the write paths ───────────────────────────────────────

def test_purchase_path_checks_the_event_date_and_cancellation():
    """
    Guards against a well-meaning refactor removing them. The listing status
    check alone is not enough: a listing stays `active` right through the
    concert unless something explicitly ends it.
    """
    import inspect

    import app.routes.bookings as bookings

    source = inspect.getsource(bookings.initiate_booking)
    assert "cancelled_at" in source, "a cancelled concert must block checkout"
    assert "already started" in source, "a finished concert must block checkout"


def test_listing_creation_checks_the_event_date_and_cancellation():
    import inspect

    import app.routes.listings as listings

    source = inspect.getsource(listings._validate_event_city)
    assert "cancelled_at" in source
    assert "already started" in source


def test_the_listing_query_selects_what_the_guard_needs():
    """
    The check reads `events.date` and `events.cancelled_at` off the joined row.
    If someone trims the select back to `events(title)` the guard silently sees
    None and stops guarding, which is worse than not having it.
    """
    import inspect

    import app.routes.bookings as bookings

    source = inspect.getsource(bookings.initiate_booking)
    assert "events(title, date, cancelled_at)" in source


# ── Browse endpoints still filter ─────────────────────────────────────────────

def test_browse_endpoints_exclude_cancelled_events():
    import inspect

    import app.routes.events as events
    import app.routes.listings as listings

    assert 'is_("cancelled_at", "null")' in inspect.getsource(events.list_events)
    assert 'is_("events.cancelled_at", "null")' in inspect.getsource(listings.list_listings)


def test_single_event_page_reports_status_rather_than_404ing():
    """
    An old link should say "this show was cancelled", not look broken. Safe
    because selling and buying are blocked at their own endpoints.
    """
    import inspect

    import app.routes.events as events

    source = inspect.getsource(events.get_event)
    for flag in ("is_cancelled", "is_past", "is_sellable"):
        assert flag in source
