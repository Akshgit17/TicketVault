"""
Synthetic training data for the pricing models.

WHY THIS FILE EXISTS, STATED PLAINLY
------------------------------------
TicketVault has zero completed transactions, so there are no real labels to
train on. There is no way around that. The choice is between a black-box CSV
from somewhere and a demand model whose assumptions are written down and
arguable — this is the second one.

Every relationship below is a stated hypothesis about how concert resale
behaves. They are all falsifiable, and once real sales accrue in
`pricing_recommendations`, this file is what gets replaced. Nothing here is
presented as measurement.

WHAT IS REAL AND WHAT IS NOT
----------------------------
  real      event catalogue, venues, cities, city tiers, face values,
            popularity tiers (curated by an admin)
  synthetic whether a listing sold, and at what price

DISCLOSE THIS. Stated openly it is ordinary practice; discovered by an examiner
it looks like a claim of results that were never measured.

Usage:
    python ml/generate_dataset.py --rows 6000 --out ml/data/listings.csv
"""
from __future__ import annotations

import argparse
import csv
import math
import random
from dataclasses import dataclass, asdict
from pathlib import Path

# ── The demand model ─────────────────────────────────────────────────────────
#
# P(sells before the event) is a logistic function of a demand score:
#
#     score = base
#           + w_pop   * (popularity_tier - 3)      more famous  -> sells more
#           + w_city  * (2 - city_tier)            metro        -> sells more
#           + w_price * (price_ratio - 1)          above face   -> sells less
#           + w_days  * f(days_until_event)        very close   -> sells less
#           + w_supply* (competing_listings)       crowded      -> sells less
#           + w_wknd  * is_weekend
#
# The dominant term is price_ratio, by design and by construction — it is the
# only one the seller controls, so it is the one the model must be sharpest on.

WEIGHTS = {
    "base":     0.55,
    "w_pop":    0.85,   # a tier-5 act is dramatically easier to sell than tier-1
    "w_city":   0.30,
    "w_price": -3.20,   # asking 20% over face costs ~0.64 of log-odds
    "w_days":   0.45,
    "w_supply": -0.28,
    "w_wknd":   0.35,
}

# How much the sale price drifts below the ask when a ticket does sell. Resale
# rarely clears at exactly the asking price.
CLEARING_DISCOUNT_MEAN = 0.03
CLEARING_DISCOUNT_SD = 0.04

# Face values by popularity tier (rupees). Loosely matches Indian concert
# pricing: club shows at the bottom, stadium tours at the top.
FACE_VALUE_BANDS = {
    1: (600, 1800),
    2: (1000, 3000),
    3: (1500, 5000),
    4: (2500, 9000),
    5: (4000, 20000),
}

CITY_TIERS = [1, 2, 3]
CITY_TIER_WEIGHTS = [0.45, 0.35, 0.20]


@dataclass
class Row:
    event_id: int
    popularity_tier: int
    city_tier: int
    venue_capacity_tier: int
    face_value: float
    price: float
    price_ratio: float
    days_until_event: int
    is_weekend: int
    competing_listings: int
    listing_age_hours: int
    sold: int
    sale_price: float | None


def days_factor(days: int) -> float:
    """
    Sell-through against time to the event.

    Hypothesis: a listing needs runway. Months out, demand is thin because few
    people are shopping yet; a few weeks out is the sweet spot; inside a couple
    of days, buyers have already made plans. Peaks around three weeks.
    """
    if days <= 0:
        return -1.5
    return math.log1p(days) / 3.0 - (days / 120.0) ** 2


def demand_score(r: dict) -> float:
    w = WEIGHTS
    return (
        w["base"]
        + w["w_pop"] * (r["popularity_tier"] - 3)
        + w["w_city"] * (2 - r["city_tier"])
        + w["w_price"] * (r["price_ratio"] - 1.0)
        + w["w_days"] * days_factor(r["days_until_event"])
        + w["w_supply"] * r["competing_listings"]
        + w["w_wknd"] * r["is_weekend"]
    )


def sigmoid(x: float) -> float:
    if x < -60:
        return 0.0
    if x > 60:
        return 1.0
    return 1.0 / (1.0 + math.exp(-x))


def generate(n_events: int, rows_per_event: int, seed: int) -> list[Row]:
    rng = random.Random(seed)
    rows: list[Row] = []

    for event_id in range(n_events):
        # Event-level attributes are shared by every listing for that event.
        # This is why the train/test split must be BY EVENT — listings for the
        # same show are not independent observations.
        popularity = rng.choices([1, 2, 3, 4, 5], weights=[0.15, 0.25, 0.30, 0.20, 0.10])[0]
        city_tier = rng.choices(CITY_TIERS, weights=CITY_TIER_WEIGHTS)[0]
        capacity_tier = min(3, max(1, round(rng.gauss(popularity * 0.6, 0.7))))
        lo, hi = FACE_VALUE_BANDS[popularity]
        face_value = round(rng.uniform(lo, hi), -1)
        is_weekend = 1 if rng.random() < 0.55 else 0

        for _ in range(rows_per_event):
            # Sellers ask anywhere from a deep discount to well over face. The
            # long right tail is what teaches the model that greed does not
            # clear — without it there is nothing to learn from.
            price_ratio = max(0.4, min(2.5, rng.lognormvariate(-0.06, 0.26)))
            price = round(face_value * price_ratio, -1)
            days = rng.randint(1, 110)
            competing = rng.choices([0, 1, 2, 3, 5, 8], weights=[.28, .26, .18, .13, .09, .06])[0]
            age_hours = rng.randint(0, 24 * 30)

            feat = {
                "popularity_tier": popularity,
                "city_tier": city_tier,
                "price_ratio": price / face_value,
                "days_until_event": days,
                "is_weekend": is_weekend,
                "competing_listings": competing,
            }
            p = sigmoid(demand_score(feat))
            sold = 1 if rng.random() < p else 0

            sale_price = None
            if sold:
                discount = max(0.0, rng.gauss(CLEARING_DISCOUNT_MEAN, CLEARING_DISCOUNT_SD))
                sale_price = round(price * (1 - discount), -1)

            rows.append(Row(
                event_id=event_id,
                popularity_tier=popularity,
                city_tier=city_tier,
                venue_capacity_tier=capacity_tier,
                face_value=face_value,
                price=price,
                price_ratio=round(price / face_value, 4),
                days_until_event=days,
                is_weekend=is_weekend,
                competing_listings=competing,
                listing_age_hours=age_hours,
                sold=sold,
                sale_price=sale_price,
            ))

    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--events", type=int, default=400)
    ap.add_argument("--per-event", type=int, default=15)
    ap.add_argument("--seed", type=int, default=20260801)
    ap.add_argument("--out", type=Path, default=Path("ml/data/listings.csv"))
    args = ap.parse_args()

    rows = generate(args.events, args.per_event, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)

    with args.out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(asdict(rows[0]).keys()))
        writer.writeheader()
        for r in rows:
            writer.writerow(asdict(r))

    sold = sum(r.sold for r in rows)
    print(f"Wrote {len(rows):,} rows across {args.events} events -> {args.out}")
    print(f"Sell-through: {sold / len(rows):.1%}")
    print(f"Seed: {args.seed} (change it and the labels change — the models do not)")


if __name__ == "__main__":
    main()
