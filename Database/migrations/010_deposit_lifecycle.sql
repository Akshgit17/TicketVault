-- 010 — Deposit lifecycle
--
-- The seller's upfront payment is a REFUNDABLE SECURITY DEPOSIT, not a fee.
-- It is returned in full when the transfer completes, and forfeited when the
-- seller fails to deliver — at which point it funds the buyer's compensation
-- and the platform retains the remainder.
--
-- Until now it was collected and never returned, on any path, while the sell
-- page promised "you get all of it back". This migration adds the state the
-- return and forfeiture paths need to be idempotent and auditable.
--
-- NOTE: no BEGIN/COMMIT around the enum changes. Postgres allows
-- ALTER TYPE ... ADD VALUE inside a transaction, but the new value cannot be
-- USED until that transaction commits — and the table changes below do not
-- reference the values, so running unwrapped is both correct and simpler.

-- ── LEDGER KINDS ─────────────────────────────────────────────────────────────
-- Money moves that had no vocabulary before. Amounts stay positive and the
-- direction carries the sign, per the existing ledger contract.
--
--   deposit        IN  — seller's deposit captured when the listing goes live
--   deposit_return OUT — returned in full on a completed transfer
--   forfeit        OUT — deposit retained by the platform after seller default
--   compensation   OUT — paid to the buyer out of a forfeited deposit
--
-- A listing's deposit entries always net to zero:
--   returned:  +D -D                    = 0
--   forfeited: +D -compensation -forfeit = 0

ALTER TYPE ledger_kind ADD VALUE IF NOT EXISTS 'deposit';
ALTER TYPE ledger_kind ADD VALUE IF NOT EXISTS 'deposit_return';
ALTER TYPE ledger_kind ADD VALUE IF NOT EXISTS 'forfeit';
ALTER TYPE ledger_kind ADD VALUE IF NOT EXISTS 'compensation';

-- ── LISTING DEPOSIT STATE ────────────────────────────────────────────────────
-- Timestamps rather than a status enum: a deposit is returned XOR forfeited,
-- and both are one-way. Nullable columns make "has this already happened?"
-- a single unambiguous check, which is what the idempotency guards use.

ALTER TABLE listings
  ADD COLUMN IF NOT EXISTS deposit_paid_paise    BIGINT,
  ADD COLUMN IF NOT EXISTS deposit_returned_at   TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS deposit_refund_id     TEXT,
  ADD COLUMN IF NOT EXISTS deposit_forfeited_at  TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS deposit_forfeit_reason TEXT;

-- A deposit cannot be both returned and forfeited. Enforced here rather than
-- trusted to application code, because the two paths run from different jobs.
ALTER TABLE listings
  DROP CONSTRAINT IF EXISTS deposit_single_outcome;
ALTER TABLE listings
  ADD CONSTRAINT deposit_single_outcome CHECK (
    deposit_returned_at IS NULL OR deposit_forfeited_at IS NULL
  );

CREATE INDEX IF NOT EXISTS idx_listings_deposit_open
  ON listings(id)
  WHERE deposit_returned_at IS NULL AND deposit_forfeited_at IS NULL;
