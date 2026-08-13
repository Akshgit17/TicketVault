"""
Price guidance.

TWO LAYERS, AND THE SEPARATION IS THE WHOLE DESIGN
--------------------------------------------------
    cap       "not abnormally high"        deterministic. A rule. Cannot fail.
    guidance  "priced to the market"       a model. Advisory. May degrade.

The instinct is to let the model enforce the ceiling. Don't. A model that is
wrong on one input then permits a ₹40,000 listing, and every trust guarantee
downstream — the price cap in the marketing, the buyer's reason to use this
instead of a group chat — rests on a number nobody validated.

The rule guarantees safety. The model optimises within it. `price_cap_paise`
below never consults the model, and the model's output is clamped to it.

DEGRADATION
-----------
This module must never raise into a request. A pricing box that quietly falls
back is invisible; one that throws takes the sell page down. Every failure —
missing artifact, sklearn not installed, an unseen event — lands on a lower
rung of the ladder and reports which rung via `source`:

    model  ->  median  ->  rules  ->  face_value

`source` is logged with every recommendation, so a silent degradation to rules
is visible in the evaluation data instead of being scored as if the model made
the call.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

from app.config import LISTING_FEE_RATE, PRICE_CAP_MULTIPLIER
from app.services.payments import to_paise

logger = logging.getLogger(__name__)

# Backend/app/services/pricing.py -> repo root
ARTIFACT_PATH = (
    Path(__file__).resolve().parents[3] / "ml" / "artifacts" / "pricing_model.joblib"
)

_artifact: dict[str, Any] | None = None
_load_attempted = False


def _load_artifact() -> dict[str, Any] | None:
    """
    Load once, lazily, and never retry a failure within the process.

    Lazy so that importing this module cannot slow or break app startup, and
    so a deployment without the artifact still serves every other route.
    """
    global _artifact, _load_attempted
    if _load_attempted:
        return _artifact
    _load_attempted = True

    if not ARTIFACT_PATH.exists():
        logger.warning(
            "Pricing model not found at %s; serving rule-based guidance. "
            "Run: python ml/train.py", ARTIFACT_PATH,
        )
        return None

    try:
        import joblib  # imported here: an optional dependency, not a startup one
        _artifact = joblib.load(ARTIFACT_PATH)
        logger.info("Pricing model %s loaded", _artifact.get("version"))
    except Exception:
        logger.exception("Could not load the pricing model; falling back to rules")
        _artifact = None

    return _artifact


# ── Layer 1: the cap (deterministic, never the model) ─────────────────────────

def price_cap_paise(face_value_paise: int) -> int:
    """
    The hard ceiling. A constraint, not a prediction.

    Mirrored by a CHECK constraint in the database, so a bug here cannot let a
    listing through anyway.
    """
    return int(face_value_paise * PRICE_CAP_MULTIPLIER)


# ── Layer 2: guidance (may degrade) ───────────────────────────────────────────

def _rules_band(face_value_paise: int, days_until_event: int | None) -> dict:
    """
    Deterministic fallback when no model is available.

    Face value, nudged by how close the event is: a show months away has room
    to ask a little over, one that is days away does not. Crude on purpose —
    its job is to always produce a sane number, not to be clever.
    """
    d = days_until_event if days_until_event is not None else 30
    if d <= 3:
        centre = 0.82
    elif d <= 10:
        centre = 0.92
    elif d <= 45:
        centre = 1.02
    else:
        centre = 0.97

    return {
        "p25": int(face_value_paise * (centre - 0.12)),
        "p50": int(face_value_paise * centre),
        "p75": int(face_value_paise * (centre + 0.12)),
    }


def _rules_probability(price_paise: int, face_value_paise: int, days_until_event: int | None) -> float:
    """Logistic in the price ratio. Same shape as the trained model, no data."""
    ratio = price_paise / face_value_paise if face_value_paise else 1.0
    d = days_until_event if days_until_event is not None else 30
    score = 1.4 - 3.2 * (ratio - 1.0) + (0.4 if 7 <= d <= 60 else -0.3)
    return round(1.0 / (1.0 + math.exp(-score)), 3)


def suggest(
    *,
    face_value_paise: int,
    days_until_event: int | None = None,
    popularity_tier: int | None = None,
    city_tier: int | None = None,
    venue_capacity_tier: int | None = None,
    is_weekend: bool | None = None,
    competing_listings: int = 0,
    proposed_price_paise: int | None = None,
) -> dict:
    """
    A recommended band, a sell probability, and the cap.

    Never raises. Always returns every key.
    """
    if face_value_paise <= 0:
        raise ValueError("face value must be positive")

    ctx = {
        "face_value_paise":    face_value_paise,
        "days_until_event":    days_until_event,
        "popularity_tier":     popularity_tier,
        "city_tier":           city_tier,
        "venue_capacity_tier": venue_capacity_tier,
        "is_weekend":          is_weekend,
        "competing_listings":  competing_listings,
    }

    cap = price_cap_paise(face_value_paise)
    artifact = _load_artifact()
    source = "rules"
    band = _rules_band(face_value_paise, days_until_event)

    if artifact is not None:
        try:
            band = _model_band(artifact, ctx)
            source = "model"
        except Exception:
            logger.exception("Pricing model failed; falling back to rules")
            band = _rules_band(face_value_paise, days_until_event)
            source = "rules"

    # The model advises; the rule decides. Clamp regardless of source, so a bad
    # prediction can never surface a price the platform would refuse anyway.
    for key in ("p25", "p50", "p75"):
        band[key] = max(1, min(int(band[key]), cap))
    # Clamping can invert the ordering when the cap bites.
    band["p25"], band["p50"], band["p75"] = sorted(
        (band["p25"], band["p50"], band["p75"])
    )

    price_for_probability = proposed_price_paise or band["p50"]
    probability = _probability(
        artifact, source, price_for_probability, face_value_paise,
        days_until_event, popularity_tier, city_tier,
        venue_capacity_tier, is_weekend, competing_listings,
    )

    return {
        "p25_paise": band["p25"],
        "p50_paise": band["p50"],
        "p75_paise": band["p75"],
        "cap_paise": cap,
        "sell_probability": probability,
        "source": source,
        "model_version": (artifact or {}).get("version"),
        # Surfaced so the UI can show the seller what they get back.
        "deposit_rate": LISTING_FEE_RATE,
    }


def _features(ctx: dict) -> list[float]:
    """
    Order must match BAND_FEATURES in ml/train.py.

    Missing values become the dataset's mid-points rather than zero: a zero
    popularity tier is not "unknown", it is "off the bottom of the scale", and
    the model would read it that way.
    """
    return [
        float(ctx.get("popularity_tier") or 3),
        float(ctx.get("city_tier") or 2),
        float(ctx.get("venue_capacity_tier") or 2),
        float(math.log1p((ctx["face_value_paise"] or 0) / 100.0)),  # trained on rupees
        float(ctx.get("days_until_event") if ctx.get("days_until_event") is not None else 30),
        float(1 if ctx.get("is_weekend") else 0),
        float(ctx.get("competing_listings") or 0),
    ]


def _model_band(artifact: dict, ctx: dict) -> dict:
    import numpy as np

    x = np.array([_features(ctx)])
    face = ctx["face_value_paise"]
    out = {}
    for key in ("p25", "p50", "p75"):
        ratio = float(artifact["band_models"][key].predict(x)[0])
        out[key] = int(face * ratio)
    return out


def _probability(
    artifact, source, price_paise, face_value_paise, days, pop, city,
    capacity, weekend, competing,
) -> float:
    if artifact is None or source != "model":
        return _rules_probability(price_paise, face_value_paise, days)

    try:
        import numpy as np

        ctx = {
            "face_value_paise": face_value_paise,
            "days_until_event": days,
            "popularity_tier": pop,
            "city_tier": city,
            "venue_capacity_tier": capacity,
            "is_weekend": weekend,
            "competing_listings": competing,
        }
        row = _features(ctx) + [price_paise / face_value_paise]
        return round(float(artifact["prob_model"].predict_proba(np.array([row]))[0][1]), 3)
    except Exception:
        logger.exception("Sell-probability prediction failed; using rules")
        return _rules_probability(price_paise, face_value_paise, days)


def rupees_to_paise(value) -> int:
    return to_paise(value)
