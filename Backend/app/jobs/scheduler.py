"""
Background scheduling.

Replaces `auto_confirm.py`, which was named after a job that no longer exists.

WHAT WAS REMOVED AND WHY
------------------------
`run_auto_confirm` was written for the QR handoff model. It marked a booking
`auto_confirmed` two hours after payment if the buyer had not acted, on the
theory that a buyer who could see a QR image and said nothing had accepted it.

The transfer redesign made that both meaningless and quietly harmful:

  * It never filtered on `fulfillment_status`, and settlement still stamps a
    two hour `confirmation_deadline` on every booking. So two hours after any
    purchase it flipped a booking that was still `awaiting_transfer` to
    `auto_confirmed`, inventing a second "confirmed" state alongside the real
    one and asserting a transfer had been accepted when it had not happened.

  * It force-wrote the listing to `sold` unconditionally. If a refund ever
    failed part way through an SLA breach, that could flip a listing that had
    correctly returned to `pending_deposit` back onto the market.

It never caused a premature payout, because `release_due_escrow` requires
`fulfillment_status = transfer_confirmed`, which this job never set. Confirmation
is now an explicit act by the buyer, and non-action is handled by the SLA
breach path, which refunds rather than assumes consent.

`bookings.confirmation_deadline` is now written but unused. It is left in place
rather than dropped, so old rows keep their history.
"""
import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

FULFILLMENT_INTERVAL_SECONDS = 30


async def run_fulfillment_jobs():
    """
    Release expired reservations, auto-refund SLA breaches, pay out due escrow.

    Blocking Supabase and Razorpay calls, so it runs in a worker thread rather
    than on the event loop.
    """
    from fastapi.concurrency import run_in_threadpool

    from app.jobs.fulfillment_jobs import run_all

    try:
        result = await run_in_threadpool(run_all)
        released = result.get("escrow", {}).get("released") or []
        refunded = result.get("breached", {}).get("refunded") or []
        if released or refunded:
            logger.info(
                "Fulfilment jobs: released %d, refunded %d",
                len(released), len(refunded),
                extra={"released_count": len(released), "refunded_count": len(refunded)},
            )
    except Exception:
        # Never let a job failure kill the scheduler thread. The next tick
        # retries, and every job in run_all is idempotent by design.
        logger.exception("Fulfilment job run failed")


@asynccontextmanager
async def lifespan(app):
    # Every 30s, so a payout lands while the demo is still on screen rather
    # than requiring someone to curl an endpoint mid-presentation. All three
    # jobs are idempotent and status-guarded, so a short interval is cheap.
    #
    # IN-PROCESS SCHEDULING IS A SINGLE-REPLICA COMPROMISE. APScheduler runs
    # inside every API instance, so at two or more replicas these fire twice
    # concurrently. The guards make that safe rather than merely unlikely:
    # compare-and-swap updates on status, a UNIQUE constraint on
    # payouts.booking_id, and idempotency keys on every ledger row. The correct
    # production shape is external cron hitting POST /jobs/fulfillment with
    # CRON_SECRET, which already exists. Delete this job and set up the cron
    # the day you run more than one instance.
    scheduler.add_job(
        run_fulfillment_jobs,
        "interval",
        seconds=FULFILLMENT_INTERVAL_SECONDS,
        id="fulfillment",
    )

    scheduler.start()
    logger.info("Scheduler started: fulfillment every %ds", FULFILLMENT_INTERVAL_SECONDS)
    yield
    scheduler.shutdown()
