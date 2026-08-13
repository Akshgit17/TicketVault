"""
Seller payout onboarding.

Creates a Razorpay Route linked account for a seller so `payouts.release_payout`
has somewhere to send money.

⚠️  THE RAZORPAY CALLS HERE ARE UNVERIFIED AGAINST LIVE ROUTE.
    Route requires marketplace onboarding (Phase 0.3), still pending. Validation,
    masking, state transitions and the storage contract are covered by tests;
    `_create_route_account` has never executed against the real API. Its exact
    request shape must be re-checked against Razorpay's docs before go-live.

STORAGE CONTRACT — do not weaken:
    The full bank account number and full PAN are used in-memory to call
    Razorpay and are then discarded. Only the last four digits of each are
    persisted, for display and support. Nothing here is ever logged.
"""
import logging
import re
from datetime import datetime, timezone

from app.database import supabase
from app.services.razorpay import client

logger = logging.getLogger(__name__)

UTC = timezone.utc

# IFSC: 4 letters, then 0, then 6 alphanumerics (RBI format).
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
# Indian bank account numbers vary by bank; 9-18 digits covers all of them.
ACCOUNT_RE = re.compile(r"^\d{9,18}$")
# PAN: 5 letters, 4 digits, 1 letter.
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")


class SellerAccountError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _last4(value: str) -> str:
    return value[-4:]


def validate_payout_details(
    *, account_number: str, ifsc: str, beneficiary_name: str, pan: str
) -> dict:
    """
    Validate before touching the provider. Returns normalised values.

    Raises SellerAccountError with a field-specific code so the UI can point at
    the offending input rather than showing one generic failure.
    """
    account_number = (account_number or "").strip()
    ifsc = (ifsc or "").strip().upper()
    beneficiary_name = (beneficiary_name or "").strip()
    pan = (pan or "").strip().upper()

    if not ACCOUNT_RE.match(account_number):
        raise SellerAccountError(
            "invalid_account_number",
            "Account number must be 9 to 18 digits.",
        )
    if not IFSC_RE.match(ifsc):
        raise SellerAccountError(
            "invalid_ifsc",
            "IFSC must look like HDFC0001234.",
        )
    if len(beneficiary_name) < 3:
        raise SellerAccountError(
            "invalid_beneficiary_name",
            "Enter the account holder's name as it appears at the bank.",
        )
    if not PAN_RE.match(pan):
        raise SellerAccountError(
            "invalid_pan",
            "PAN must look like ABCDE1234F.",
        )

    return {
        "account_number": account_number,
        "ifsc": ifsc,
        "beneficiary_name": beneficiary_name,
        "pan": pan,
    }


def _create_route_account(user: dict, details: dict) -> str:
    """
    Create the Razorpay Route linked account. Returns the linked account id.

    ⚠️ Unverified against live Route — see module docstring.
    """
    payload = {
        "email": user["email"],
        "phone": user.get("phone") or "",
        "type": "route",
        "legal_business_name": details["beneficiary_name"],
        "business_type": "individual",
        "contact_name": details["beneficiary_name"],
        "profile": {"category": "ecommerce", "subcategory": "ticketing"},
        "legal_info": {"pan": details["pan"]},
    }
    account = client.account.create(payload)
    account_id = account.get("id")
    if not account_id:
        raise SellerAccountError("provider_failed", "Payout account could not be created.")
    return account_id


def configure_payout_account(
    user: dict,
    *,
    account_number: str,
    ifsc: str,
    beneficiary_name: str,
    pan: str,
) -> dict:
    """
    Set up a seller's payout account. Idempotent: a seller who already has a
    linked account is returned as-is rather than issued a second one.
    """
    if user.get("razorpay_linked_account_id"):
        return {
            "status": "already_configured",
            "linked_account_id": user["razorpay_linked_account_id"],
        }

    details = validate_payout_details(
        account_number=account_number,
        ifsc=ifsc,
        beneficiary_name=beneficiary_name,
        pan=pan,
    )

    try:
        linked_account_id = _create_route_account(user, details)
    except SellerAccountError:
        raise
    except Exception:
        # Never let the provider's exception text propagate — it can echo back
        # the submitted account number.
        logger.exception("Route account creation failed for user %s", user["id"])
        raise SellerAccountError(
            "provider_failed",
            "Could not set up your payout account. Please try again.",
        )

    # Persist only the masked remnants. The full values go out of scope here.
    supabase.table("users").update({
        "razorpay_linked_account_id": linked_account_id,
        "payout_account_last4":       _last4(details["account_number"]),
        "payout_ifsc":                details["ifsc"],
        "payout_beneficiary_name":    details["beneficiary_name"],
        "pan_last4":                  _last4(details["pan"]),
        "kyc_status":                 "pending",
        "payout_configured_at":       datetime.now(UTC).isoformat(),
    }).eq("id", user["id"]).execute()

    logger.info(
        "Payout account configured for user %s", user["id"],
        extra={"user_id": user["id"], "linked_account_id": linked_account_id},
    )

    return {
        "status": "configured",
        "linked_account_id": linked_account_id,
        "kyc_status": "pending",
    }


def payout_status(user: dict) -> dict:
    """Masked view of a seller's payout setup, safe to return to the client."""
    configured = bool(user.get("razorpay_linked_account_id"))
    return {
        "configured": configured,
        "kyc_status": user.get("kyc_status", "none"),
        "payout_hold": bool(user.get("payout_hold")),
        "account_last4": user.get("payout_account_last4"),
        "ifsc": user.get("payout_ifsc"),
        "beneficiary_name": user.get("payout_beneficiary_name"),
        "can_receive_payouts": configured and not user.get("payout_hold"),
    }


def can_sell(user: dict) -> tuple[bool, str | None]:
    """
    Whether a seller may create listings.

    A seller who cannot be paid should not be able to take a buyer's money.
    Gated behind REQUIRE_PAYOUT_ACCOUNT so it can ship before Route is live.
    """
    from app.config import REQUIRE_PAYOUT_ACCOUNT

    if not REQUIRE_PAYOUT_ACCOUNT:
        return True, None
    if not user.get("razorpay_linked_account_id"):
        return False, "Add your payout account before listing a ticket."
    if user.get("payout_hold"):
        return False, "Your account is under review and cannot list tickets."
    return True, None
