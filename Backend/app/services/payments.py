"""
Payment verification.

A valid Razorpay signature proves only that *a* payment happened — not which one,
and not for how much. Verification must therefore bind the payment to the specific
order we are settling, and confirm the amount server-side.

All settlement paths (bookings, listing fees) go through `verify_payment_for`.
"""
import logging

from app.services.razorpay import client, verify_payment

logger = logging.getLogger(__name__)


class PaymentVerificationError(Exception):
    """Raised when a payment cannot be safely attributed to the expected order."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def to_paise(amount_inr: float) -> int:
    """Convert rupees to paise the same way create_order does, so comparisons match."""
    return int(round(float(amount_inr) * 100))


def verify_payment_for(
    *,
    expected_order_id: str | None,
    expected_amount_paise: int,
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
) -> dict:
    """
    Verify that a client-reported payment genuinely settles `expected_order_id`
    for `expected_amount_paise`.

    Checks, in order (cheapest and most decisive first):
      1. The client's order id matches the order we created for this record.
         Without this, any valid receipt settles any record — pay 1 rupee on
         your own listing, replay the receipt, claim a 50,000 rupee ticket.
      2. The HMAC signature is valid for (order_id, payment_id).
      3. Razorpay itself reports the order as paid, for the expected amount.
         The client is never trusted for the amount.

    Returns the fetched Razorpay order on success.
    Raises PaymentVerificationError otherwise.
    """
    if not expected_order_id:
        raise PaymentVerificationError(
            "no_order",
            "No payment was initiated for this record.",
        )

    if razorpay_order_id != expected_order_id:
        logger.warning(
            "Order binding failed: client sent %s, expected %s",
            razorpay_order_id,
            expected_order_id,
        )
        raise PaymentVerificationError(
            "order_mismatch",
            "Payment does not belong to this order.",
        )

    if not verify_payment(
        razorpay_order_id=razorpay_order_id,
        razorpay_payment_id=razorpay_payment_id,
        razorpay_signature=razorpay_signature,
    ):
        raise PaymentVerificationError(
            "invalid_signature",
            "Payment verification failed. Invalid signature.",
        )

    try:
        order = client.order.fetch(razorpay_order_id)
    except Exception as e:
        # Never settle on an unverifiable order — fail closed.
        logger.error("Razorpay order fetch failed for %s: %s", razorpay_order_id, e)
        raise PaymentVerificationError(
            "verification_unavailable",
            "Could not verify payment with the payment provider. Please retry.",
        )

    if order.get("status") != "paid":
        raise PaymentVerificationError(
            "order_not_paid",
            f"Order is not paid (status: {order.get('status')}).",
        )

    if int(order.get("amount", -1)) != int(expected_amount_paise):
        logger.warning(
            "Amount mismatch on %s: razorpay=%s expected=%s",
            razorpay_order_id,
            order.get("amount"),
            expected_amount_paise,
        )
        raise PaymentVerificationError(
            "amount_mismatch",
            "Paid amount does not match the order total.",
        )

    return order
