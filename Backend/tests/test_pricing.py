"""
Price guidance.

The properties that matter here are not accuracy — that is measured in
ml/artifacts/metrics.json against held-out events. They are:

  * the cap is deterministic and the model can never widen it,
  * guidance degrades instead of raising, on every failure path,
  * the caller can always tell which rung of the ladder answered.

A pricing box that quietly falls back is invisible to a user. One that throws
takes the sell page down.
"""
import pytest

import app.services.pricing as pricing
from app.config import PRICE_CAP_MULTIPLIER

FACE = 500_000  # ₹5,000 in paise


@pytest.fixture(autouse=True)
def reset_artifact_cache():
    """The module caches its load; tests must not inherit each other's state."""
    pricing._artifact = None
    pricing._load_attempted = False
    yield
    pricing._artifact = None
    pricing._load_attempted = False


# ── Layer 1: the cap ──────────────────────────────────────────────────────────

def test_cap_is_a_pure_function_of_face_value():
    assert pricing.price_cap_paise(FACE) == int(FACE * PRICE_CAP_MULTIPLIER)


def test_cap_does_not_consult_the_model(monkeypatch):
    """
    If the cap ever depended on the model, a bad prediction could raise the
    ceiling — and every trust guarantee downstream rests on that number.
    """
    def explode(*_a, **_k):
        raise AssertionError("the cap must never load the model")

    monkeypatch.setattr(pricing, "_load_artifact", explode)
    assert pricing.price_cap_paise(FACE) > 0


# ── Layer 2: guidance ─────────────────────────────────────────────────────────

def test_band_is_clamped_to_the_cap(monkeypatch):
    """A model predicting an absurd ratio must not surface an illegal price."""
    class Greedy:
        def predict(self, _x):
            return [9.0]  # 900% of face value

    monkeypatch.setattr(pricing, "_load_artifact", lambda: {
        "version": "test",
        "band_models": {"p25": Greedy(), "p50": Greedy(), "p75": Greedy()},
        "prob_model": None,
    })

    out = pricing.suggest(face_value_paise=FACE)
    cap = pricing.price_cap_paise(FACE)

    assert out["p75_paise"] <= cap
    assert out["p50_paise"] <= cap
    assert out["p25_paise"] <= cap


def test_band_stays_ordered_after_clamping(monkeypatch):
    class Fixed:
        def __init__(self, r): self.r = r
        def predict(self, _x): return [self.r]

    monkeypatch.setattr(pricing, "_load_artifact", lambda: {
        "version": "test",
        "band_models": {"p25": Fixed(1.1), "p50": Fixed(3.0), "p75": Fixed(0.4)},
        "prob_model": None,
    })

    out = pricing.suggest(face_value_paise=FACE)
    assert out["p25_paise"] <= out["p50_paise"] <= out["p75_paise"]


def test_missing_artifact_degrades_to_rules(monkeypatch):
    monkeypatch.setattr(pricing, "_load_artifact", lambda: None)

    out = pricing.suggest(face_value_paise=FACE, days_until_event=20)

    assert out["source"] == "rules"
    assert out["p25_paise"] < out["p75_paise"]
    assert 0.0 <= out["sell_probability"] <= 1.0


def test_broken_model_degrades_instead_of_raising(monkeypatch):
    class Broken:
        def predict(self, _x):
            raise RuntimeError("corrupt artifact")

    monkeypatch.setattr(pricing, "_load_artifact", lambda: {
        "version": "test",
        "band_models": {"p25": Broken(), "p50": Broken(), "p75": Broken()},
        "prob_model": None,
    })

    out = pricing.suggest(face_value_paise=FACE)

    assert out["source"] == "rules", "a broken model must not take the page down"
    assert out["cap_paise"] == pricing.price_cap_paise(FACE)


def test_every_key_is_always_present(monkeypatch):
    monkeypatch.setattr(pricing, "_load_artifact", lambda: None)
    out = pricing.suggest(face_value_paise=FACE)

    for key in (
        "p25_paise", "p50_paise", "p75_paise", "cap_paise",
        "sell_probability", "source", "model_version",
    ):
        assert key in out, f"callers rely on {key} always existing"


def test_rejects_non_positive_face_value():
    with pytest.raises(ValueError):
        pricing.suggest(face_value_paise=0)


# ── Behaviour the product depends on ──────────────────────────────────────────

def test_asking_more_lowers_the_sell_probability(monkeypatch):
    """
    The core interaction: drag the price up, watch the probability fall. If
    this inverts, the slider actively misleads sellers.
    """
    monkeypatch.setattr(pricing, "_load_artifact", lambda: None)

    cheap = pricing.suggest(
        face_value_paise=FACE, proposed_price_paise=int(FACE * 0.8), days_until_event=30
    )
    dear = pricing.suggest(
        face_value_paise=FACE, proposed_price_paise=int(FACE * 1.19), days_until_event=30
    )

    assert cheap["sell_probability"] > dear["sell_probability"]


def test_missing_features_do_not_break_cold_start(monkeypatch):
    """A brand new event with no tier, no venue history, no competition."""
    monkeypatch.setattr(pricing, "_load_artifact", lambda: None)

    out = pricing.suggest(
        face_value_paise=FACE,
        days_until_event=None,
        popularity_tier=None,
        city_tier=None,
    )
    assert out["p50_paise"] > 0
