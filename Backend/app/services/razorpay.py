import razorpay
from app.config import settings

client = razorpay.Client(
    auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
)


def create_order(amount_inr: float, receipt: str, notes: dict = {}) -> dict:
    """
    Create a Razorpay order.
    amount_inr: amount in INR — converted to paise (×100).
    Returns the full Razorpay order object.
    """
    order = client.order.create({
        "amount":   int(round(amount_inr * 100)),
        "currency": "INR",
        "receipt":  receipt[:40],      # max 40 chars
        "notes":    notes,
    })
    return order


def verify_payment(razorpay_order_id: str, razorpay_payment_id: str, razorpay_signature: str) -> bool:
    """
    Verify Razorpay payment signature.
    Returns True if signature is valid.
    """
    try:
        client.utility.verify_payment_signature({
            "razorpay_order_id":   razorpay_order_id,
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_signature":  razorpay_signature,
        })
        return True
    except Exception:
        return False
