import logging
import secrets
import time

from fastapi import APIRouter, Header, HTTPException, Response

from app.database import supabase
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get("/health/live")
def liveness():
    """Process is up. Never touches dependencies — safe for restart probes."""
    return {"status": "ok"}


@router.get("/health")
def health(response: Response):
    """
    Readiness. Returns 503 when a critical dependency is unavailable.

    Previously this always returned HTTP 200 with {"status": "ok"} even when the
    database check failed, so no load balancer or uptime monitor would ever pull
    the instance out of rotation.
    """
    checks: dict[str, dict] = {}

    started = time.perf_counter()
    try:
        supabase.table("cities").select("id").limit(1).execute()
        checks["database"] = {
            "status": "ok",
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }
    except Exception as e:
        logger.error("Health check: database unreachable: %s", e)
        checks["database"] = {"status": "error"}

    # Configuration checks only — health must not spend a live API call, and
    # must not be rate-limited by the provider.
    checks["razorpay"] = {
        "status": "ok" if settings.RAZORPAY_KEY_ID else "unconfigured",
    }
    checks["webhook_secret"] = {
        "status": "ok" if settings.RAZORPAY_WEBHOOK_SECRET not in ("", "dummy") else "unconfigured",
    }

    healthy = checks["database"]["status"] == "ok"
    if not healthy:
        response.status_code = 503

    return {
        "status": "ok" if healthy else "degraded",
        "environment": settings.ENVIRONMENT,
        "checks": checks,
    }


@router.post("/jobs/fulfillment")
def trigger_fulfillment_jobs(x_cron_secret: str = Header(...)):
    """
    Reservation expiry, SLA auto-refunds, and escrow release.

    Run every few minutes from external cron. Deliberately not on the in-process
    scheduler, which runs in every replica and would double-fire.
    """
    if not secrets.compare_digest(x_cron_secret, settings.CRON_SECRET):
        logger.warning("Rejected fulfilment trigger: bad cron secret")
        raise HTTPException(status_code=403, detail="Forbidden")

    from app.jobs.fulfillment_jobs import run_all

    return run_all()


@router.post("/jobs/reconcile")
def trigger_reconcile(response: Response, x_cron_secret: str = Header(...)):
    """
    Daily money reconciliation. Run from external cron.

    Returns 409 when discrepancies are found, so a cron monitor treats a drift
    as a failed run and alerts, rather than a silent 200 nobody reads.
    """
    if not secrets.compare_digest(x_cron_secret, settings.CRON_SECRET):
        logger.warning("Rejected reconcile trigger: bad cron secret")
        raise HTTPException(status_code=403, detail="Forbidden")

    from app.jobs.reconcile import find_discrepancies

    report = find_discrepancies()
    if report["issue_count"]:
        response.status_code = 409
    return report
