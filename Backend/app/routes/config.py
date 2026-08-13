from fastapi import APIRouter

from app.config import (
    BUYER_COMPENSATION_RATE,
    FULFILLMENT_SLA_HOURS,
    LISTING_FEE_RATE,
    PRICE_CAP_MULTIPLIER,
    SELLER_SUCCESS_FEE_RATE,
    SETTLEMENT_HOLD_HOURS,
    SIMULATE_PAYOUTS,
)

router = APIRouter(prefix="/config", tags=["config"])


@router.get("")
async def get_public_config():
    """
    Public business constants for the frontend.

    Exists so values like the deposit rate are defined once on the server rather
    than duplicated into client code, where they silently drift. Every number
    the UI quotes to a user about money or deadlines comes from here.
    """
    return {
        # Refundable security deposit the seller pays to publish a listing.
        # Returned on a completed transfer; forfeited on seller default.
        "listing_fee_rate":        LISTING_FEE_RATE,
        # Commission taken from the seller's proceeds on a completed sale, so
        # the sell page can show what they will actually receive rather than
        # promising the full asking price.
        "seller_success_fee_rate": SELLER_SUCCESS_FEE_RATE,
        "price_cap_multiplier":    PRICE_CAP_MULTIPLIER,
        "transfer_sla_hours":      FULFILLMENT_SLA_HOURS,
        "settlement_hold_hours":   SETTLEMENT_HOLD_HOURS,
        "buyer_compensation_rate": BUYER_COMPENSATION_RATE,
        "currency":                "INR",
        # Lets the UI state plainly that seller payouts are not real money
        # movement. Razorpay Route has required ₹40L turnover since the RBI
        # rules of Sept 2025 and was withdrawn from non-compliant merchants on
        # 1 Jan 2026, so no student project can settle to a third party.
        # Refunds — including the deposit return — are genuinely real.
        "simulated_payouts":       SIMULATE_PAYOUTS,
    }
