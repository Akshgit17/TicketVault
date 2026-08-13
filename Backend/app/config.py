import os

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

# Module-level constants below read from the environment, so .env has to be
# loaded before they are evaluated — Settings() does its own loading, but that
# happens further down the file.
load_dotenv()


def _hours(name: str, default: float) -> float:
    """
    A timing constant, overridable from .env.

    Every clock the demo has to outrun lives here. Setting
    SETTLEMENT_HOLD_HOURS=0 or FULFILLMENT_SLA_HOURS=0.01 in .env lets the
    payout and the SLA-breach paths both fire while you are still on stage,
    with no code edit and nothing to remember to change back before committing.
    """
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


# ── Business constants ────────────────────────────────────────────────────────
# Single source of truth. Previously duplicated across schema.sql (generated
# column), listings.py (twice) and sell/page.tsx. Exposed to the frontend via
# GET /config so it is never hardcoded client-side again.
#
# NOTE: the fee model itself is a Phase 0.2 decision. If the seller-side upfront
# fee is dropped in favour of a buyer-side fee, the fee endpoints are deleted
# rather than re-tuned — do not build on this constant beyond that point.
LISTING_FEE_RATE = 0.20

# Commission deducted from the seller's payout on a completed sale.
#
# This was 0.0, on the reasoning that the seller had "already paid" the 20%
# upfront. That reasoning died when the upfront charge became a REFUNDABLE
# deposit: the seller now gets all of it back, so nothing had been paid, and
# the platform was left earning nothing on a successful sale. Its only income
# was the forfeit when a seller failed, which is a bad thing for a marketplace
# to be paid for.
#
# 2% on delivery means revenue comes from transactions working.
SELLER_SUCCESS_FEE_RATE = 0.02

# Require a configured payout account before a seller can list.
#
# Correct end state is True — a seller who cannot be paid should not be able to
# take a buyer's money. Ships as False because Razorpay Route onboarding
# (Phase 0.3) is incomplete, so no seller can create a linked account yet;
# enabling this now would make listing impossible for everyone.
#
# FLIP TO TRUE the day Route goes live.
REQUIRE_PAYOUT_ACCOUNT = False

# Simulate the outbound leg of a seller payout.
#
# Razorpay Route requires marketplace onboarding with a registered business
# entity, which this project does not have — so `client.transfer.create` can
# never succeed here and no seller can hold a linked account. With Route
# unavailable, an unsimulated payout fails permanently and the booking
# lifecycle can never reach its terminal state.
#
# When True: the payout row, the fee split, the ledger entries and every state
# transition are real and auditable; only the outbound bank transfer is stood
# in for, with a clearly-marked synthetic transfer id (`sim_...`). Nothing
# pretends money left the account.
#
# FLIP TO FALSE the day Route goes live — the code path either side is the
# same, and payouts.py is covered by tests in both modes.
SIMULATE_PAYOUTS = os.getenv("SIMULATE_PAYOUTS", "true").strip().lower() in {"1", "true", "yes"}

# ── Fulfilment (Phase 3) ──────────────────────────────────────────────────────

# How long a seller has to complete the issuer-side transfer once the transfer
# window is open. Breaching this auto-refunds the buyer.
#
# 24 hours, not 6. The clock runs around the wall clock, not around working
# hours, so a 6-hour window means a ticket bought at 2am expires before the
# seller wakes up. Forfeiting someone's deposit for sleeping is not a fraud
# control, it is a bug with a moral tone.
#
# 24 hours guarantees every seller sees at least one full waking day. It costs
# the buyer some certainty, which is the right trade: a buyer waiting a day is
# inconvenienced, whereas an honest seller losing a deposit overnight is
# actively wronged.
#
# THE REAL FIX IS NOTIFICATIONS, WHICH DO NOT EXIST YET. There is no email or
# SMS anywhere in this system, so a seller only learns their ticket sold by
# happening to log in. A deadline nobody is told about cannot be enforced
# fairly at any length. Until notifications ship, treat this number as
# generous on purpose. See docs/COLLEGE_PROJECT_PLAN.md Part D.
FULFILLMENT_SLA_HOURS = _hours("FULFILLMENT_SLA_HOURS", 24)

# RETIRED — kept only so an old value in someone's notes does not look current.
#
# Escrow used to release 24 hours after the EVENT. That was correct for the QR
# model, where a screenshot's validity is unknowable until the gate. The
# transfer model puts an issuer-validated ticket in the buyer's own account, so
# the wait no longer buys anything: release now runs from buyer confirmation
# plus SETTLEMENT_HOLD_HOURS. See fulfillment.confirm_transfer_received.
ESCROW_RELEASE_HOURS_AFTER_EVENT = 24  # unused

# How long a listing stays reserved during checkout before returning to market.
RESERVATION_MINUTES = 15

# Hold between the buyer confirming receipt and the seller being paid, leaving
# room to report a mis-transfer (wrong date, wrong seat, wrong event).
#
# This is now what actually drives the release job, via
# fulfillment.confirm_transfer_received.
#
# Set this to a small value for demos — the payout should land while you are
# still on the page, without editing code. 0 releases on the next job run.
SETTLEMENT_HOLD_HOURS = _hours("SETTLEMENT_HOLD_HOURS", 6)

# Hard ceiling on resale price, as a multiple of face value.
#
# Deterministic on purpose. The pricing model recommends a band *within* this
# cap but never sets it — a learned ceiling is a ceiling nobody validated, and
# every trust guarantee downstream depends on this number holding.
PRICE_CAP_MULTIPLIER = 1.2

# How a forfeited deposit is divided when a seller fails to transfer.
#
# Expressed as a share of the DEPOSIT rather than of the ticket price, which is
# what makes it stable. The old form paid the buyer a fixed 10% of the price
# and let the platform keep whatever was left, so the 50/50 split was a
# coincidence of two independent constants: change the deposit rate to 15% and
# the buyer would silently start receiving two thirds of it.
#
# Defining the share directly also makes over-payment structurally impossible.
# A half of the deposit can never exceed the deposit, so there is no arithmetic
# path to compensating a buyer with money that was never collected, including
# after the seller has repriced the listing.
PLATFORM_FORFEIT_SHARE = 0.50

# Effective compensation as a fraction of the ticket price, DERIVED so it can
# never drift from the split above. Exposed via GET /config purely so the UI
# can quote a number to buyers and sellers before anything has gone wrong.
BUYER_COMPENSATION_RATE = LISTING_FEE_RATE * (1 - PLATFORM_FORFEIT_SHARE)


class Settings(BaseSettings):
    SUPABASE_URL: str
    SUPABASE_SERVICE_KEY: str
    CLERK_JWT_ISSUER: str
    RAZORPAY_KEY_ID: str
    RAZORPAY_KEY_SECRET: str
    RAZORPAY_WEBHOOK_SECRET: str = "dummy"
    CRON_SECRET: str = "changeme"

    # ── Observability ─────────────────────────────────────────────────────────
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "console"          # "console" locally, "json" in deployment
    SENTRY_DSN: str = ""                 # empty disables error reporting
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0

    class Config:
        env_file = ".env"
        # Tolerate keys in .env that Settings does not declare.
        #
        # The timing constants above (FULFILLMENT_SLA_HOURS,
        # SETTLEMENT_HOLD_HOURS, SIMULATE_PAYOUTS) are read with os.getenv
        # rather than declared as fields. Without this, pydantic sees them in
        # .env, treats them as unexpected input and refuses to construct
        # Settings at all, so setting a demo override crashes the entire app on
        # import. A config file that cannot be added to is not a config file.
        extra = "ignore"


settings = Settings()
