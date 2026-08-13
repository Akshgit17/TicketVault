"""
Phase 2.2 — seller payout onboarding.

The most important tests here are the storage-contract ones: a database dump
must not contain a usable bank account number or a full PAN.
"""
import json
import logging

import pytest

import app.services.seller_accounts as sa
from tests.conftest import SELLER, patch_supabase
from tests.fake_supabase import FakeSupabase

VALID = {
    "account_number": "000111222333",
    "ifsc": "HDFC0001234",
    "beneficiary_name": "A Sharma",
    "pan": "ABCDE1234F",
}


@pytest.fixture
def db(monkeypatch):
    fake = FakeSupabase({"users": [dict(SELLER)]})
    patch_supabase(monkeypatch, fake)
    return fake


@pytest.fixture
def rzp(monkeypatch):
    class FakeAccounts:
        def __init__(self):
            self.created = []

        def create(self, payload):
            self.created.append(payload)
            return {"id": f"acc_{len(self.created)}"}

    class FakeClient:
        def __init__(self):
            self.account = FakeAccounts()

    fake = FakeClient()
    monkeypatch.setattr(sa, "client", fake)
    return fake


# ── Validation ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "field,value,code",
    [
        ("account_number", "12345",              "invalid_account_number"),  # too short
        ("account_number", "1234567890123456789", "invalid_account_number"), # too long
        ("account_number", "12345678a",          "invalid_account_number"),  # non-numeric
        ("ifsc",           "HDFC1001234",        "invalid_ifsc"),            # 5th char not 0
        ("ifsc",           "HD0F0001234",        "invalid_ifsc"),
        ("ifsc",           "",                   "invalid_ifsc"),
        ("beneficiary_name", "A",                "invalid_beneficiary_name"),
        ("pan",            "ABCD1234F",          "invalid_pan"),             # 4 letters
        ("pan",            "ABCDE12345",         "invalid_pan"),             # ends numeric
    ],
)
def test_invalid_details_are_rejected(field, value, code):
    payload = {**VALID, field: value}
    with pytest.raises(sa.SellerAccountError) as e:
        sa.validate_payout_details(**payload)
    assert e.value.code == code


def test_valid_details_are_normalised():
    out = sa.validate_payout_details(
        account_number=" 000111222333 ",
        ifsc="hdfc0001234",
        beneficiary_name="  A Sharma ",
        pan="abcde1234f",
    )
    assert out["ifsc"] == "HDFC0001234"
    assert out["pan"] == "ABCDE1234F"
    assert out["account_number"] == "000111222333"
    assert out["beneficiary_name"] == "A Sharma"


def test_validation_happens_before_the_provider_is_called(db, rzp):
    """Bad input must never reach Razorpay."""
    with pytest.raises(sa.SellerAccountError):
        sa.configure_payout_account(db.get("users", SELLER["id"]), **{**VALID, "ifsc": "nope"})
    assert rzp.account.created == []


# ── Storage contract ──────────────────────────────────────────────────────────

def test_full_account_number_and_pan_are_never_persisted(db, rzp):
    sa.configure_payout_account(db.get("users", SELLER["id"]), **VALID)

    stored = json.dumps(db.rows("users"))
    assert VALID["account_number"] not in stored, "full account number was persisted"
    assert VALID["pan"] not in stored, "full PAN was persisted"

    user = db.get("users", SELLER["id"])
    assert user["payout_account_last4"] == "2333"
    assert user["pan_last4"] == "234F"
    assert user["razorpay_linked_account_id"] == "acc_1"
    assert user["kyc_status"] == "pending"


def test_sensitive_values_are_never_logged(db, rzp, caplog):
    with caplog.at_level(logging.DEBUG):
        sa.configure_payout_account(db.get("users", SELLER["id"]), **VALID)

    logged = "\n".join(r.getMessage() for r in caplog.records)
    logged += json.dumps([r.__dict__ for r in caplog.records], default=str)
    assert VALID["account_number"] not in logged
    assert VALID["pan"] not in logged


def test_provider_errors_do_not_echo_submitted_values(db, monkeypatch):
    """A provider exception can quote the request body back at us."""
    class Leaky:
        class account:
            @staticmethod
            def create(payload):
                raise RuntimeError(f"invalid account {VALID['account_number']} / {VALID['pan']}")

    monkeypatch.setattr(sa, "client", Leaky())

    with pytest.raises(sa.SellerAccountError) as e:
        sa.configure_payout_account(db.get("users", SELLER["id"]), **VALID)

    assert e.value.code == "provider_failed"
    assert VALID["account_number"] not in e.value.message
    assert VALID["pan"] not in e.value.message


def test_status_response_exposes_only_masked_data(db, rzp):
    sa.configure_payout_account(db.get("users", SELLER["id"]), **VALID)
    status = sa.payout_status(db.get("users", SELLER["id"]))

    body = json.dumps(status)
    assert VALID["account_number"] not in body
    assert VALID["pan"] not in body
    assert status["account_last4"] == "2333"
    assert status["can_receive_payouts"] is True


# ── Idempotency and gating ────────────────────────────────────────────────────

def test_configuring_twice_does_not_create_a_second_account(db, rzp):
    sa.configure_payout_account(db.get("users", SELLER["id"]), **VALID)
    second = sa.configure_payout_account(db.get("users", SELLER["id"]), **VALID)

    assert second["status"] == "already_configured"
    assert len(rzp.account.created) == 1


def test_payout_hold_blocks_receiving_money(db, rzp):
    sa.configure_payout_account(db.get("users", SELLER["id"]), **VALID)
    db.get("users", SELLER["id"])["payout_hold"] = True

    assert sa.payout_status(db.get("users", SELLER["id"]))["can_receive_payouts"] is False


def test_gate_is_disabled_by_default(db):
    """Ships off, because Route onboarding is incomplete and nobody could list."""
    from app.config import REQUIRE_PAYOUT_ACCOUNT

    assert REQUIRE_PAYOUT_ACCOUNT is False
    allowed, reason = sa.can_sell(dict(SELLER))
    assert allowed is True and reason is None


def test_gate_blocks_unconfigured_seller_when_enabled(db, monkeypatch):
    monkeypatch.setattr("app.config.REQUIRE_PAYOUT_ACCOUNT", True)

    allowed, reason = sa.can_sell(dict(SELLER))
    assert allowed is False
    assert "payout account" in reason.lower()


def test_gate_allows_configured_seller_when_enabled(db, rzp, monkeypatch):
    sa.configure_payout_account(db.get("users", SELLER["id"]), **VALID)
    monkeypatch.setattr("app.config.REQUIRE_PAYOUT_ACCOUNT", True)

    allowed, reason = sa.can_sell(db.get("users", SELLER["id"]))
    assert allowed is True and reason is None


def test_gate_blocks_seller_on_hold_when_enabled(db, rzp, monkeypatch):
    sa.configure_payout_account(db.get("users", SELLER["id"]), **VALID)
    db.get("users", SELLER["id"])["payout_hold"] = True
    monkeypatch.setattr("app.config.REQUIRE_PAYOUT_ACCOUNT", True)

    allowed, reason = sa.can_sell(db.get("users", SELLER["id"]))
    assert allowed is False
    assert "review" in reason.lower()
