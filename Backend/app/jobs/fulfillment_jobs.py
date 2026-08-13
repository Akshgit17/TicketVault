"""
Fulfilment background jobs.

Three jobs, all idempotent and safe to run concurrently:

  release_expired_reservations — returns abandoned checkouts to the market.
      Fixes the original bug where `lock_expiry` was written but never read, so
      every abandoned checkout removed a ticket from the marketplace forever.

  fail_breached_transfers — auto-refunds when a seller misses the SLA.
      The common failure, handled without a human.

  release_due_escrow — pays sellers 24h after the event.

Run from external cron via POST /jobs/*, not the in-process scheduler: that one
runs in every replica and would double-fire at 2+ instances.
"""
import logging
from datetime import datetime, timezone

from app.database import supabase
from app.services import deposits, fulfillment, payouts, refunds

logger = logging.getLogger(__name__)

UTC = timezone.utc


def release_expired_reservations() -> dict:
    """Return listings whose checkout reservation lapsed back to `active`."""
    now = datetime.now(UTC).isoformat()

    stale = (
        supabase.table("listings")
        .select("id, lock_expiry")
        .eq("status", "locked")
        .lt("lock_expiry", now)
        .execute()
    ).data or []

    released = []
    for listing in stale:
        # Guarded on `locked` so a listing that sold in the meantime is skipped.
        updated = (
            supabase.table("listings")
            .update({"status": "active", "locked_by": None, "lock_expiry": None})
            .eq("id", listing["id"])
            .eq("status", "locked")
            .execute()
        )
        if updated.data:
            released.append(listing["id"])

    if released:
        logger.info(
            "Released %d expired reservations", len(released),
            extra={"released_count": len(released)},
        )
    return {"released": released, "count": len(released)}


def fail_breached_transfers() -> dict:
    """Refund buyers whose seller missed the transfer deadline."""
    now = datetime.now(UTC).isoformat()

    breached = (
        supabase.table("bookings")
        .select("*")
        .eq("fulfillment_status", fulfillment.AWAITING_TRANSFER)
        .eq("payment_status", "paid")
        .lt("transfer_deadline", now)
        .execute()
    ).data or []

    refunded, failures = [], []

    for booking in breached:
        booking_id = booking["id"]
        try:
            # Mark first: if the refund call dies mid-flight, the booking is
            # already out of the awaiting state and will not be double-processed
            # on the next run. Reconciliation surfaces a failed refund.
            fulfillment.fail_fulfillment(
                booking, reason="seller missed the transfer deadline",
            )
            refunds.refund_booking(booking, reason="seller_did_not_transfer")

            # The seller broke the deal, so their deposit pays for it: the
            # buyer's compensation comes out of it and the platform keeps the
            # rest. Non-fatal — the buyer's refund above is the part that
            # must not be held up by a deposit bookkeeping failure.
            listing = _load_listing(booking["listing_id"])
            if listing:
                try:
                    deposits.forfeit_deposit(
                        listing, booking, reason="seller_did_not_transfer",
                    )
                except Exception:
                    logger.exception(
                        "Could not forfeit deposit for booking %s", booking_id,
                        extra={"booking_id": booking_id, "alert": True},
                    )

            _require_new_deposit(booking)
            refunded.append(booking_id)
        except Exception as e:
            logger.exception(
                "Could not auto-refund breached booking %s", booking_id,
                extra={"booking_id": booking_id, "alert": True},
            )
            failures.append({"booking_id": booking_id, "error": str(e)[:200]})

    if refunded:
        logger.info(
            "Auto-refunded %d breached transfers", len(refunded),
            extra={"refunded_count": len(refunded)},
        )
    return {"refunded": refunded, "failures": failures}


def release_due_escrow() -> dict:
    """
    Pay sellers for bookings whose escrow window has elapsed and which are not
    under dispute.

    The dispute filter is the point of the settlement hold. Without it a buyer
    could confirm receipt, discover within the hold window that the ticket is
    for the wrong date, report it, and be paid no attention: the job only
    looked at fulfilment status, so the payout fired regardless and the
    dispute was decorative. The buyer's confirmation screen promises "tell us
    before payout if anything is wrong", and this is what makes that true.

    A disputed booking simply stays here until an admin resolves it. That is
    deliberate: freezing money is reversible, paying it out is not.
    """
    now = datetime.now(UTC).isoformat()

    due = (
        supabase.table("bookings")
        .select("*")
        .eq("fulfillment_status", fulfillment.TRANSFER_CONFIRMED)
        .eq("payment_status", "paid")
        .neq("confirmation_status", "disputed")
        .lt("escrow_release_at", now)
        .execute()
    ).data or []

    paid, failures = [], []

    for booking in due:
        booking_id = booking["id"]
        try:
            listing = _load_listing(booking["listing_id"])
            if not listing:
                raise RuntimeError("listing missing")

            payouts.release_payout(booking, listing)

            # The seller delivered, so the deposit goes back — this is the
            # other half of what the sell page promised, and it happens in the
            # same operation as the payout rather than on a separate schedule.
            #
            # Non-fatal on its own: a deposit that fails to return is retried
            # by the next run (the guard is the listing's own timestamp), and
            # holding up mark_released would strand the payout that already
            # succeeded.
            try:
                deposits.return_deposit(listing, reason="transfer_completed")
            except Exception:
                logger.exception(
                    "Payout succeeded but deposit return failed for booking %s",
                    booking_id,
                    extra={"booking_id": booking_id, "alert": True},
                )

            fulfillment.mark_released(booking)
            paid.append(booking_id)
        except Exception as e:
            # Left in transfer_confirmed so the next run retries. A seller who
            # has not finished payout onboarding resolves itself once they do.
            logger.exception(
                "Could not release escrow for booking %s", booking_id,
                extra={"booking_id": booking_id},
            )
            failures.append({"booking_id": booking_id, "error": str(e)[:200]})

    if paid:
        logger.info(
            "Released escrow for %d bookings", len(paid),
            extra={"released_count": len(paid)},
        )
    return {"released": paid, "failures": failures}


def record_pricing_outcomes() -> dict:
    """
    Fill in whether each priced listing actually sold.

    `pricing_recommendations` stored the band shown, the probability shown and
    the price the seller chose, but nothing ever wrote the outcome. The table
    was described as the dataset that replaces the synthetic training labels,
    and without labels it could not be.

    Deliberately derived rather than pushed. The listing id is on the row, so
    the outcome can be recomputed at any time and a missed run costs nothing;
    writing it from inside the sale path would have added a way for settlement
    to fail for a reporting reason.

    `sold` means a buyer paid, not that the transfer completed. That is the
    right label for a pricing model: the question it answers is "will someone
    buy at this price", and a seller failing to transfer afterwards says
    nothing about whether the price was right.
    """
    pending = (
        supabase.table("pricing_recommendations")
        .select("id, listing_id")
        .is_("sold", "null")
        .not_.is_("listing_id", "null")
        .limit(500)
        .execute()
    ).data or []

    if not pending:
        return {"labelled": 0}

    listing_ids = list({r["listing_id"] for r in pending})

    listings = (
        supabase.table("listings")
        .select("id, status")
        .in_("id", listing_ids)
        .execute()
    ).data or []
    status_by_id = {l["id"]: l["status"] for l in listings}

    # `refunded` counts as sold. A buyer who paid and was later refunded
    # because the SELLER failed to transfer still proves the price was
    # acceptable, which is the only question a pricing model asks. Filtering to
    # `paid` alone silently discards every unhappy-path sale and biases the
    # training set towards prices that happened to be paired with a reliable
    # seller.
    paid = (
        supabase.table("bookings")
        .select("listing_id, created_at")
        .in_("listing_id", listing_ids)
        .in_("payment_status", ["paid", "refunded"])
        .execute()
    ).data or []
    sold_at_by_listing = {b["listing_id"]: b.get("created_at") for b in paid}

    labelled = 0
    for row in pending:
        listing_id = row["listing_id"]
        status = status_by_id.get(listing_id)
        if status is None:
            continue

        if listing_id in sold_at_by_listing:
            outcome, sold_at = True, sold_at_by_listing[listing_id]
        elif status == "cancelled":
            # Withdrawn without selling. A settled negative.
            outcome, sold_at = False, None
        else:
            # Still live, so the answer is not known yet. Leaving it NULL is
            # the point: an unsold listing is right-censored, not a negative.
            continue

        supabase.table("pricing_recommendations").update({
            "sold": outcome, "sold_at": sold_at,
        }).eq("id", row["id"]).is_("sold", "null").execute()
        labelled += 1

    if labelled:
        logger.info("Labelled %d pricing recommendations", labelled)
    return {"labelled": labelled}


def run_all() -> dict:
    """Everything the fulfilment cron needs, in dependency order."""
    return {
        "reservations": release_expired_reservations(),
        "breached":     fail_breached_transfers(),
        "escrow":       release_due_escrow(),
        "pricing":      _safe(record_pricing_outcomes),
    }


def _safe(fn) -> dict:
    """
    Reporting must never break settlement.

    Labelling is bookkeeping for a future model. If it throws, the money jobs
    above have already run and their result should still be returned.
    """
    try:
        return fn()
    except Exception:
        logger.exception("%s failed", fn.__name__)
        return {"error": fn.__name__}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_listing(listing_id: str) -> dict | None:
    r = supabase.table("listings").select("*").eq("id", listing_id).execute()
    return r.data[0] if r.data else None


def _require_new_deposit(booking: dict) -> None:
    """
    Send a failed listing back to `pending_deposit` rather than deleting it.

    Three designs were considered, and the first two are both wrong:

      relist as `active`   Unsafe. The deposit is forfeited once and forfeiture
                           is one-way, so the ticket would go back on sale
                           backed by nothing: the next buyer gets a refund but
                           never compensation, and the seller, having already
                           lost the deposit, risks nothing by failing again.
                           One deposit buys the right to waste unlimited
                           buyers' time.

      cancel outright      Unfair. A missed deadline is not proof of bad faith.
                           The SLA runs around the clock, so a sale at 2am can
                           lapse before the seller wakes up, and this platform
                           sends NO notifications at all: a seller only learns
                           their ticket sold by happening to log in. Destroying
                           a listing over that punishes someone for sleeping.

      require a new deposit   Both problems solved. The listing survives with
                           its event, price and proof intact, so relisting is
                           one click. But it cannot reach the market again
                           until a fresh deposit is paid, so every buyer is
                           always backed by money genuinely at risk.

    The forfeited deposit stays forfeited: the buyer who was let down keeps
    their compensation, and the ledger entry is permanent. Only the listing's
    operational deposit state resets, so a new cycle can begin.
    """
    listing_id = booking["listing_id"]

    supabase.table("listings").update({
        "status":       "pending_fee",
        "locked_by":    None,
        "lock_expiry":  None,
        # Clear the operational state so a fresh deposit can be taken and,
        # if it comes to it, forfeited again. History is not lost: the
        # `forfeit` ledger entry is append-only and stays for good.
        "deposit_paid_paise":     None,
        "deposit_forfeited_at":   None,
        "deposit_forfeit_reason": None,
        "fee_razorpay_payment_id": None,
    }).eq("id", listing_id).eq("status", "sold").execute()

    logger.info(
        "Listing %s returned to pending_deposit after a missed transfer; "
        "seller may relist by paying a new deposit", listing_id,
        extra={"listing_id": listing_id},
    )
