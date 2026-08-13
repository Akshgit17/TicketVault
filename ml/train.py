"""
Train the two pricing models and write a single serving artifact.

MODEL A — price band
    Quantile regression at P25/P50/P75 on `sale_price / face_value`, fitted on
    SOLD listings only. It answers "what do tickets for a show like this
    actually clear at?", so it must learn from prices that cleared. Predicting
    the *ratio* rather than the rupee price is what lets an ₹800 club show and
    an ₹18,000 arena tour share one model.

    A band, never a point. A single number invites "why exactly ₹4,217?" and
    there is no honest answer.

MODEL B — sell probability
    P(sells before the event | price, everything else), fitted on all rows.
    This is the one that makes the product feel intelligent, because it turns
    pricing from a guess into a visible trade-off.

    Its labels are imperfect and it is worth being able to say why: an unsold
    listing is RIGHT-CENSORED, not a negative example — it has not sold *yet*.
    The statistically correct treatment is a discrete-time survival model.
    This trains the simpler binary classifier and names the limitation.

WHY scikit-learn AND NOT LightGBM
    HistGradientBoosting gives quantile regression and a calibrated-enough
    classifier out of the box, and drops a heavy binary dependency that is a
    known install hazard in CI. On a few-thousand-row dataset the accuracy
    difference is noise, and the deployment cost is not.

Usage:
    python ml/train.py
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import brier_score_loss, mean_absolute_error, roc_auc_score

MODEL_VERSION = "1.0.0"

# Model A never sees price_ratio — that is its target.
BAND_FEATURES = [
    "popularity_tier", "city_tier", "venue_capacity_tier",
    "log_face_value", "days_until_event", "is_weekend", "competing_listings",
]

# Model B does, and it is the dominant feature: the only one a seller controls.
PROB_FEATURES = BAND_FEATURES + ["price_ratio"]

QUANTILES = {"p25": 0.25, "p50": 0.50, "p75": 0.75}


def load(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["log_face_value"] = np.log1p(df["face_value"])
    return df


def split_by_event(df: pd.DataFrame, test_frac: float, seed: int):
    """
    Hold out whole EVENTS, never individual rows.

    Listings for the same show share every event-level feature, so a random row
    split leaks the answer across the boundary and inflates every metric. This
    is the single easiest way to accidentally report a great model that cannot
    price a show it has not seen — and it is worth saying out loud that the
    split is by event, because most people do not do it.
    """
    rng = np.random.default_rng(seed)
    events = df["event_id"].unique()
    rng.shuffle(events)
    n_test = max(1, int(len(events) * test_frac))
    test_events = set(events[:n_test])

    is_test = df["event_id"].isin(test_events)
    return df[~is_test].copy(), df[is_test].copy()


def train_band(train: pd.DataFrame, test: pd.DataFrame):
    sold_train = train[train["sold"] == 1].copy()
    sold_test = test[test["sold"] == 1].copy()

    for frame in (sold_train, sold_test):
        frame["target_ratio"] = frame["sale_price"] / frame["face_value"]

    models, report = {}, {}
    for name, q in QUANTILES.items():
        m = HistGradientBoostingRegressor(
            loss="quantile", quantile=q,
            max_iter=300, learning_rate=0.06, max_depth=6,
            min_samples_leaf=20, random_state=7,
        )
        # .to_numpy(), not the DataFrame. Fitting on named columns makes
        # sklearn record the feature names and then warn on every prediction
        # made from a plain array — which is how the service calls it, once per
        # keystroke on the price slider. Training array-in means inference needs
        # only numpy, with no pandas dependency and no log spam.
        m.fit(sold_train[BAND_FEATURES].to_numpy(), sold_train["target_ratio"].to_numpy())
        models[name] = m

    pred = {name: m.predict(sold_test[BAND_FEATURES].to_numpy()) for name, m in models.items()}
    actual = sold_test["target_ratio"].to_numpy()

    # Baseline worth beating: "just price at face value". If the model cannot
    # beat this, that is a finding and should be reported as one.
    baseline_mae = mean_absolute_error(actual, np.ones_like(actual))

    inside = np.mean((actual >= pred["p25"]) & (actual <= pred["p75"]))
    report = {
        "n_train_sold": int(len(sold_train)),
        "n_test_sold": int(len(sold_test)),
        "mae_p50": float(mean_absolute_error(actual, pred["p50"])),
        "baseline_mae_face_value": float(baseline_mae),
        # Should land near 0.50. Far off means the quantiles are miscalibrated
        # and the band is lying about its own confidence.
        "p25_p75_coverage": float(inside),
    }
    return models, report


def train_probability(train: pd.DataFrame, test: pd.DataFrame):
    base = HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.06, max_depth=6,
        min_samples_leaf=20, random_state=7,
    )

    # Wrapped in isotonic calibration, and this is not decoration.
    #
    # The raw booster was badly underconfident at the bottom of the range: it
    # predicted 4% where 19% actually sold. That error points the wrong way for
    # this product — it would talk a seller out of a price that would in fact
    # have cleared. Since the number is shown to a human as "~X% likely to
    # sell", being right *on average within each bucket* matters more than
    # ranking listings correctly, which is what AUC measures.
    #
    # Isotonic rather than sigmoid: the miscalibration is not a neat S-curve,
    # and there is enough data here for the non-parametric fit.
    clf = CalibratedClassifierCV(base, method="isotonic", cv=3)
    clf.fit(train[PROB_FEATURES].to_numpy(), train["sold"].to_numpy())

    proba = clf.predict_proba(test[PROB_FEATURES].to_numpy())[:, 1]
    y = test["sold"].to_numpy()

    # Calibration matters more than AUC here. The number is shown to a user as
    # "~80% likely to sell", so it has to mean 80% — a model can rank perfectly
    # and still be systematically overconfident.
    bins = np.linspace(0, 1, 11)
    idx = np.clip(np.digitize(proba, bins) - 1, 0, 9)
    calibration = []
    for b in range(10):
        mask = idx == b
        if mask.sum() >= 10:
            calibration.append({
                "bucket": f"{bins[b]:.1f}-{bins[b+1]:.1f}",
                "predicted": float(proba[mask].mean()),
                "actual": float(y[mask].mean()),
                "n": int(mask.sum()),
            })

    report = {
        "n_train": int(len(train)),
        "n_test": int(len(test)),
        "auc": float(roc_auc_score(y, proba)),
        "brier": float(brier_score_loss(y, proba)),
        "brier_baseline_base_rate": float(
            brier_score_loss(y, np.full_like(proba, train["sold"].mean()))
        ),
        "calibration": calibration,
    }
    return clf, report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, default=Path("ml/data/listings.csv"))
    ap.add_argument("--out", type=Path, default=Path("ml/artifacts/pricing_model.joblib"))
    ap.add_argument("--report", type=Path, default=Path("ml/artifacts/metrics.json"))
    ap.add_argument("--test-frac", type=float, default=0.25)
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()

    df = load(args.data)
    train, test = split_by_event(df, args.test_frac, args.seed)

    band_models, band_report = train_band(train, test)
    prob_model, prob_report = train_probability(train, test)

    artifact = {
        "version": MODEL_VERSION,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "band_features": BAND_FEATURES,
        "prob_features": PROB_FEATURES,
        "band_models": band_models,
        "prob_model": prob_model,
        # Used by the service's cold-start ladder when a feature is missing.
        "global_median_ratio": float(
            (df.loc[df["sold"] == 1, "sale_price"] / df.loc[df["sold"] == 1, "face_value"]).median()
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, args.out)

    metrics = {
        "model_version": MODEL_VERSION,
        "split": "by event (not by row)",
        "n_events_total": int(df["event_id"].nunique()),
        "band": band_report,
        "probability": prob_report,
        "known_limitations": [
            "Labels are synthetic — see ml/generate_dataset.py for the demand model.",
            "Unsold listings are right-censored, not negatives; survival analysis is the correct treatment.",
        ],
    }
    args.report.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    print(f"\nArtifact  -> {args.out}")
    print(f"Metrics   -> {args.report}\n")
    print("MODEL A — price band")
    print(f"  MAE (P50 vs actual ratio) : {band_report['mae_p50']:.4f}")
    print(f"  Baseline (price at face)  : {band_report['baseline_mae_face_value']:.4f}")
    print(f"  P25-P75 coverage          : {band_report['p25_p75_coverage']:.1%}  (target ~50%)")
    print("\nMODEL B — sell probability")
    print(f"  AUC                       : {prob_report['auc']:.4f}")
    print(f"  Brier                     : {prob_report['brier']:.4f}")
    print(f"  Brier (base-rate baseline): {prob_report['brier_baseline_base_rate']:.4f}")
    print("\n  calibration (predicted -> actual)")
    for row in prob_report["calibration"]:
        print(f"    {row['bucket']:>9}  {row['predicted']:.2f} -> {row['actual']:.2f}  (n={row['n']})")


if __name__ == "__main__":
    main()
