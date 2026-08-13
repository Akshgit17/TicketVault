-- 011 — Pricing intelligence
--
-- Two additions:
--   1. Demand signals on `events`, so a price can be reasoned about at all.
--   2. `pricing_recommendations` — a log of every suggestion made, what the
--      seller actually chose, and whether it sold.
--
-- The log matters more than it looks. It is simultaneously the future training
-- set, the live calibration check (does a predicted 80% actually sell 80% of
-- the time?), and the evidence that guidance changes behaviour. It is also the
-- one thing here that cannot be back-filled — a suggestion not logged the day
-- it was shown is gone. Everything else in this project can be rebuilt later.

BEGIN;

-- ── DEMAND SIGNALS ───────────────────────────────────────────────────────────

-- Curated 1–5 popularity, set by an admin. This is a FIRST-CLASS feature, not
-- a fallback for when an API lookup fails.
--
-- Reason: Last.fm's userbase skews heavily Western, so it systematically
-- understates Indian acts — a playback singer who sells out an arena in
-- Hyderabad can show fewer listeners than a mid-tier Western indie band. Since
-- this catalogue is Indian concerts, that is the typical case, not an edge
-- case, and a model trained on raw listener counts would price the
-- highest-demand shows in the country too low. The curated tier lets a human
-- correct the external signal rather than merely substitute for it.
ALTER TABLE events
  ADD COLUMN IF NOT EXISTS popularity_tier SMALLINT
    CHECK (popularity_tier BETWEEN 1 AND 5);

-- Optional Last.fm enrichment. Nullable on purpose: the pipeline must work
-- without an API key, and name-matching against Last.fm fails often enough
-- ("X Live in Concert", collaborations, spellings) that it cannot be required.
ALTER TABLE events
  ADD COLUMN IF NOT EXISTS lastfm_artist     TEXT,
  ADD COLUMN IF NOT EXISTS lastfm_listeners  BIGINT,
  ADD COLUMN IF NOT EXISTS lastfm_fetched_at TIMESTAMPTZ;

-- Metro / tier-1 / tier-2 rather than the raw city id. With every city in
-- scope and a modest dataset, a high-cardinality categorical makes the model
-- memorise cities instead of learning demand — and tiers generalise to a city
-- it has never seen.
ALTER TABLE cities
  ADD COLUMN IF NOT EXISTS city_tier SMALLINT NOT NULL DEFAULT 2
    CHECK (city_tier BETWEEN 1 AND 3);

UPDATE cities SET city_tier = 1
 WHERE name IN ('Mumbai', 'New Delhi', 'Bengaluru');
UPDATE cities SET city_tier = 2
 WHERE name IN ('Hyderabad', 'Chennai', 'Pune', 'Kolkata', 'Ahmedabad');
UPDATE cities SET city_tier = 3
 WHERE city_tier IS NULL OR name IN ('Goa', 'Jaipur', 'Kochi', 'Chandigarh', 'Indore');

-- Sensible default so nothing is NULL on day one; admins refine from there.
UPDATE events SET popularity_tier = 3 WHERE popularity_tier IS NULL;


-- ── RECOMMENDATION LOG ───────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS pricing_recommendations (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  event_id      UUID REFERENCES events(id)   ON DELETE SET NULL,
  seller_id     UUID REFERENCES users(id)    ON DELETE SET NULL,
  -- Set once the seller actually creates the listing, so a recommendation can
  -- be joined to its outcome.
  listing_id    UUID REFERENCES listings(id) ON DELETE SET NULL,

  -- What we were asked about.
  face_value_paise BIGINT NOT NULL CHECK (face_value_paise > 0),
  features         JSONB  NOT NULL DEFAULT '{}'::jsonb,

  -- What we said. Storing the band rather than a point estimate, because a
  -- point estimate invites "why exactly this number?" and has no answer.
  p25_paise     BIGINT,
  p50_paise     BIGINT,
  p75_paise     BIGINT,
  cap_paise     BIGINT NOT NULL,
  sell_probability REAL CHECK (sell_probability BETWEEN 0 AND 1),

  -- Which rung of the fallback ladder produced this: model | median | rules |
  -- face_value. Without it, a quiet degradation to rules is invisible in the
  -- evaluation data and would be scored as if the model had made the call.
  source        TEXT NOT NULL,
  model_version TEXT,

  -- What the seller did about it.
  chosen_price_paise BIGINT,
  accepted           BOOLEAN,   -- did they take a price inside the band?

  -- How it turned out. Filled in later by the outcome backfill.
  sold          BOOLEAN,
  sold_at       TIMESTAMPTZ,

  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pricing_rec_event
  ON pricing_recommendations(event_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pricing_rec_listing
  ON pricing_recommendations(listing_id);
CREATE INDEX IF NOT EXISTS idx_pricing_rec_outcome
  ON pricing_recommendations(sold, created_at DESC);

COMMIT;

SELECT
  (SELECT COUNT(*) FROM events WHERE popularity_tier IS NOT NULL) AS events_tiered,
  (SELECT COUNT(*) FROM cities WHERE city_tier = 1)               AS metro_cities,
  (SELECT COUNT(*) FROM pricing_recommendations)                  AS logged_recommendations;
