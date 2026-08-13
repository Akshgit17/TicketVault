-- ============================================================================
-- FIX 010 — STEP 2 of 2: the listing deposit state
-- ============================================================================
--
-- RUN STEP 1 FIRST. This file is safe on its own, but the deposit code needs
-- both halves before it works.
--
-- No BEGIN/COMMIT, no DO blocks — every statement is individually idempotent.
-- ============================================================================

-- Timestamps rather than a status enum: a deposit is returned XOR forfeited,
-- and both are one-way. Nullable columns make "has this already happened?" a
-- single unambiguous check, which is exactly what the idempotency guards in
-- app/services/deposits.py test — it is what stops a retried background job
-- refunding the same deposit twice.

ALTER TABLE listings
  ADD COLUMN IF NOT EXISTS deposit_paid_paise     BIGINT,
  ADD COLUMN IF NOT EXISTS deposit_returned_at    TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS deposit_refund_id      TEXT,
  ADD COLUMN IF NOT EXISTS deposit_forfeited_at   TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS deposit_forfeit_reason TEXT;

-- A deposit cannot be both returned and forfeited. Enforced in the database
-- rather than trusted to application code, because the two paths run from
-- different background jobs and could in principle race.
ALTER TABLE listings DROP CONSTRAINT IF EXISTS deposit_single_outcome;

ALTER TABLE listings
  ADD CONSTRAINT deposit_single_outcome CHECK (
    deposit_returned_at IS NULL OR deposit_forfeited_at IS NULL
  );

CREATE INDEX IF NOT EXISTS idx_listings_deposit_open
  ON listings(id)
  WHERE deposit_returned_at IS NULL AND deposit_forfeited_at IS NULL;


-- ── VERIFY — all six should say APPLIED ─────────────────────────────────────

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

    (10, '010a_ledger_kinds', 'deposit/forfeit/compensation enum values',
        (SELECT COUNT(*) = 4 FROM unnest(enum_range(NULL::ledger_kind)) AS v
          WHERE v::text IN ('deposit', 'deposit_return', 'forfeit', 'compensation'))),

    (11, '010b_deposit_columns', 'listings.deposit_returned_at',
        (SELECT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'listings'
                          AND column_name = 'deposit_returned_at'))),

    (12, '011_pricing', 'events.popularity_tier + pricing_recommendations',
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
