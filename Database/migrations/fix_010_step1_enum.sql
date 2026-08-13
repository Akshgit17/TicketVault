-- ============================================================================
-- FIX 010 — STEP 1 of 2: the enum values
-- ============================================================================
--
-- RUN THIS FILE ON ITS OWN, THEN RUN STEP 2 SEPARATELY.
--
-- Why it has to be split: Postgres will not let a newly added enum value be
-- USED in the same transaction that added it, and the Supabase SQL editor runs
-- your whole script inside one transaction. Migration 010 put these ALTER TYPE
-- statements in the same script as the table changes, so it failed at the first
-- statement and silently did nothing else — which is why 010 was the only one
-- of the five still missing.
--
-- Every statement is IF NOT EXISTS. Running it twice is harmless.
--
-- If the editor still complains about a transaction block, run these four
-- lines ONE AT A TIME. That always works.
--
-- ============================================================================
--
-- What these are for: the deposit is a refundable security deposit with two
-- possible endings, and the ledger had no vocabulary for either.
--
--   deposit        IN  — seller's deposit captured when the listing goes live
--   deposit_return OUT — returned in full on a completed transfer
--   forfeit        OUT — retained by the platform after a seller default
--   compensation   OUT — paid to the buyer out of a forfeited deposit
--
-- A listing's deposit entries always net to zero:
--   returned:  +D -D                     = 0
--   forfeited: +D -compensation -forfeit = 0

ALTER TYPE ledger_kind ADD VALUE IF NOT EXISTS 'deposit';

ALTER TYPE ledger_kind ADD VALUE IF NOT EXISTS 'deposit_return';

ALTER TYPE ledger_kind ADD VALUE IF NOT EXISTS 'forfeit';

ALTER TYPE ledger_kind ADD VALUE IF NOT EXISTS 'compensation';
