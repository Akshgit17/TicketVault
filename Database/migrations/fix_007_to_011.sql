-- ============================================================================
-- TicketVault — migrations 007, 008, 009 and 011, combined and unwrapped
-- ============================================================================
--
-- These four reported as run but never landed. The common factor is that each
-- wrapped itself in BEGIN; ... COMMIT; while 010 — which did land — did not.
-- The Supabase SQL Editor already executes a script inside its own
-- transaction, so a nested BEGIN warns and a mid-script COMMIT closes the
-- editor's transaction early; whatever follows can then quietly do nothing.
--
-- So this file has:
--   * NO BEGIN / COMMIT
--   * NO DO $$ ... $$ blocks — every operation is expressed as plain SQL whose
--     WHERE clause makes it a no-op when it does not apply
--   * NO dependency on execution order beyond the section order below
--
-- Every statement is idempotent. Run it as many times as you like.
--
-- ⚠️  Select nothing before hitting Run. The Supabase editor executes only the
--     highlighted text when a selection exists, which is one way a script can
--     appear to run while doing almost nothing.
--
-- The last statement reports which migrations are now present. Read it.
-- ============================================================================


-- ── 007 — merge the duplicate city ──────────────────────────────────────────
-- 'Bangalore' and 'Bengaluru' were separate rows for one city, so whichever a
-- user picked from the selector, half the catalogue was invisible.
--
-- BENGALURU SURVIVES. 'Bangalore' is merged into it and deleted, matching
-- seed.sql, which seeds 'Bengaluru' and attaches all five of its events to it.
-- Keeping the spelling the seed already uses means a reseed cannot resurrect
-- the duplicate.
--
-- Each statement is guarded by the subquery itself: if either spelling is
-- absent the subquery yields NULL, nothing matches, and the statement is a
-- no-op.

UPDATE events
   SET city_id = (SELECT id FROM cities WHERE name = 'Bengaluru')
 WHERE city_id = (SELECT id FROM cities WHERE name = 'Bangalore')
   AND EXISTS (SELECT 1 FROM cities WHERE name = 'Bengaluru');

UPDATE listings
   SET city_id = (SELECT id FROM cities WHERE name = 'Bengaluru')
 WHERE city_id = (SELECT id FROM cities WHERE name = 'Bangalore')
   AND EXISTS (SELECT 1 FROM cities WHERE name = 'Bengaluru');

UPDATE event_requests
   SET city_id = (SELECT id FROM cities WHERE name = 'Bengaluru')
 WHERE city_id = (SELECT id FROM cities WHERE name = 'Bangalore')
   AND EXISTS (SELECT 1 FROM cities WHERE name = 'Bengaluru');

DELETE FROM cities
 WHERE name = 'Bangalore'
   AND EXISTS (SELECT 1 FROM cities WHERE name = 'Bengaluru');

-- If a database somehow has only 'Bangalore', there is nothing to merge into —
-- rename it instead, so the whole project settles on one spelling either way.
UPDATE cities
   SET name = 'Bengaluru', slug = 'bengaluru'
 WHERE name = 'Bangalore'
   AND NOT EXISTS (SELECT 1 FROM cities WHERE name = 'Bengaluru');

-- Case-only duplicates ('goa' vs 'Goa') slipped past UNIQUE(name), which is
-- case-sensitive. These stop the next one appearing.
CREATE UNIQUE INDEX IF NOT EXISTS uq_cities_name_ci ON cities (LOWER(name));
CREATE UNIQUE INDEX IF NOT EXISTS uq_cities_slug_ci ON cities (LOWER(slug));


-- ── 008 — remove cities with nothing in them ────────────────────────────────
-- 16 cities, 8 with events. Every empty one is a trapdoor in the city
-- selector: pick it, get the empty state, conclude the site is broken.
-- A city comes straight back the moment you seed an event for it.

DELETE FROM cities c
 WHERE NOT EXISTS (SELECT 1 FROM events         e WHERE e.city_id = c.id)
   AND NOT EXISTS (SELECT 1 FROM listings       l WHERE l.city_id = c.id)
   AND NOT EXISTS (SELECT 1 FROM event_requests r WHERE r.city_id = c.id);


-- ── 009 — enable issuer-side transfer ───────────────────────────────────────
-- THIS IS THE ONE BLOCKING THE WALKTHROUGH.
--
-- Migration 005 added events.transfer_supported with no default, leaving every
-- row NULL. fulfillment.py reads NULL as "not transfer-enabled" and sends the
-- booking down the legacy QR path — so the seller never receives a transfer
-- task and the whole transfer UI is unreachable. A paid booking just stops.

UPDATE events SET transfer_supported = TRUE WHERE transfer_supported IS NOT TRUE;

-- New rows too, including events created by the admin approval queue. Without
-- this, every approved event request reintroduces the same trap.
ALTER TABLE events ALTER COLUMN transfer_supported SET DEFAULT TRUE;


-- ── 011 — pricing intelligence ──────────────────────────────────────────────

-- Curated 1–5 popularity, set by an admin. A FIRST-CLASS feature, not a
-- fallback: Last.fm's userbase skews Western and systematically understates
-- Indian acts, which for this catalogue is the typical case rather than an
-- edge case. The curated tier lets a human correct the external signal.
ALTER TABLE events
  ADD COLUMN IF NOT EXISTS popularity_tier SMALLINT
    CHECK (popularity_tier BETWEEN 1 AND 5);

-- Optional Last.fm enrichment. Nullable: the pipeline must work with no API
-- key, and name-matching fails often enough that it cannot be required.
ALTER TABLE events
  ADD COLUMN IF NOT EXISTS lastfm_artist     TEXT,
  ADD COLUMN IF NOT EXISTS lastfm_listeners  BIGINT,
  ADD COLUMN IF NOT EXISTS lastfm_fetched_at TIMESTAMPTZ;

-- Metro / tier-1 / tier-2 rather than a raw city id: with a modest dataset a
-- high-cardinality categorical makes the model memorise cities instead of
-- learning demand, and tiers generalise to a city it has never seen.
ALTER TABLE cities
  ADD COLUMN IF NOT EXISTS city_tier SMALLINT NOT NULL DEFAULT 2
    CHECK (city_tier BETWEEN 1 AND 3);

UPDATE cities SET city_tier = 1
 WHERE name IN ('Mumbai', 'New Delhi', 'Bengaluru');

UPDATE cities SET city_tier = 3
 WHERE name IN ('Goa', 'Jaipur', 'Kochi', 'Chandigarh', 'Indore', 'Lucknow', 'Surat');

UPDATE events SET popularity_tier = 3 WHERE popularity_tier IS NULL;

-- Every suggestion made, what the seller chose, and whether it sold.
-- Simultaneously the future training set, the live calibration check, and the
-- evidence that guidance changes behaviour — and the one thing here that
-- cannot be back-filled. A recommendation not logged the day it was shown is
-- gone for good.
CREATE TABLE IF NOT EXISTS pricing_recommendations (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  event_id      UUID REFERENCES events(id)   ON DELETE SET NULL,
  seller_id     UUID REFERENCES users(id)    ON DELETE SET NULL,
  listing_id    UUID REFERENCES listings(id) ON DELETE SET NULL,

  face_value_paise BIGINT NOT NULL CHECK (face_value_paise > 0),
  features         JSONB  NOT NULL DEFAULT '{}'::jsonb,

  -- The band, not a point estimate: a single number invites "why exactly
  -- ₹4,217?" and has no honest answer.
  p25_paise     BIGINT,
  p50_paise     BIGINT,
  p75_paise     BIGINT,
  cap_paise     BIGINT NOT NULL,
  sell_probability REAL CHECK (sell_probability BETWEEN 0 AND 1),

  -- Which rung of the fallback ladder answered: model | median | rules |
  -- face_value. Without it a quiet degradation to rules is invisible in the
  -- evaluation data and gets scored as if the model made the call.
  source        TEXT NOT NULL,
  model_version TEXT,

  chosen_price_paise BIGINT,
  accepted           BOOLEAN,

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


-- ── VERIFY ──────────────────────────────────────────────────────────────────
-- Anything still MISSING here did not apply. Do not assume — read it.

WITH checks(seq, migration, artifact, present) AS (
  VALUES
    (7, '007_city_dedupe', 'no duplicate Bangalore/Bengaluru',
        (SELECT NOT (EXISTS (SELECT 1 FROM cities WHERE name = 'Bangalore')
                 AND EXISTS (SELECT 1 FROM cities WHERE name = 'Bengaluru')))),

    (8, '008_prune_empty_cities', 'every city has at least one event',
        (SELECT NOT EXISTS (
           SELECT 1 FROM cities c
           WHERE NOT EXISTS (SELECT 1 FROM events e WHERE e.city_id = c.id)))),

    (9, '009_enable_transfer', 'all events transfer_supported = TRUE',
        (SELECT NOT EXISTS (SELECT 1 FROM events WHERE transfer_supported IS NOT TRUE))),

    (10, '010_deposit_lifecycle', 'listings.deposit_returned_at',
        (SELECT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'listings'
                          AND column_name = 'deposit_returned_at'))),

    (11, '011_pricing', 'events.popularity_tier + pricing_recommendations',
        (SELECT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'events' AND column_name = 'popularity_tier')
            AND to_regclass('public.pricing_recommendations') IS NOT NULL))
)
SELECT
  migration,
  CASE WHEN present THEN 'APPLIED' ELSE '>>> MISSING <<<' END AS status,
  artifact
FROM checks
ORDER BY seq;
