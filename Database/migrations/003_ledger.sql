-- 003_ledger.sql
-- Phase 2.1 — append-only money ledger, plus payouts and refunds.
--
-- Every movement of money gets a row. Nothing is ever updated or deleted; a
-- correction is a new `reversal` row. This is what makes reconciliation against
-- Razorpay's settlement report possible, and what lets you answer "where did
-- this 50,000 rupees go" six months later.
--
-- Amounts are BIGINT paise, never NUMERIC rupees and never floats. Money in
-- floating point accumulates error precisely where it is least acceptable.

-- ── LEDGER ────────────────────────────────────────────────────────────────────

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'ledger_direction') THEN
    CREATE TYPE ledger_direction AS ENUM ('in', 'out');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'ledger_kind') THEN
    CREATE TYPE ledger_kind AS ENUM ('capture', 'payout', 'refund', 'fee', 'reversal');
  END IF;
END
$$;

CREATE TABLE IF NOT EXISTS ledger_entries (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  booking_id      UUID REFERENCES bookings(id) ON DELETE RESTRICT,
  listing_id      UUID REFERENCES listings(id) ON DELETE RESTRICT,
  user_id         UUID REFERENCES users(id)    ON DELETE RESTRICT,
  direction       ledger_direction NOT NULL,
  kind            ledger_kind      NOT NULL,
  amount_paise    BIGINT NOT NULL CHECK (amount_paise > 0),
  currency        TEXT   NOT NULL DEFAULT 'INR',
  external_ref    TEXT,
  -- Makes recording a movement twice impossible, e.g. when a webhook is
  -- redelivered or a job is retried.
  idempotency_key TEXT NOT NULL,
  metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_ledger_idempotency UNIQUE (idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_ledger_booking ON ledger_entries(booking_id);
CREATE INDEX IF NOT EXISTS idx_ledger_user    ON ledger_entries(user_id);
CREATE INDEX IF NOT EXISTS idx_ledger_kind    ON ledger_entries(kind);
CREATE INDEX IF NOT EXISTS idx_ledger_created ON ledger_entries(created_at);

-- Enforce append-only at the database, not by convention. A future bug, an
-- admin panel, or a careless psql session cannot rewrite financial history.
CREATE OR REPLACE FUNCTION ledger_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'ledger_entries is append-only; write a reversal entry instead';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_ledger_append_only ON ledger_entries;
CREATE TRIGGER trg_ledger_append_only
  BEFORE UPDATE OR DELETE ON ledger_entries
  FOR EACH ROW EXECUTE FUNCTION ledger_append_only();

-- ── PAYOUTS ───────────────────────────────────────────────────────────────────

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'payout_status') THEN
    CREATE TYPE payout_status AS ENUM (
      'pending', 'processing', 'paid', 'failed', 'reversed'
    );
  END IF;
END
$$;

CREATE TABLE IF NOT EXISTS payouts (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  booking_id           UUID NOT NULL REFERENCES bookings(id) ON DELETE RESTRICT,
  seller_id            UUID NOT NULL REFERENCES users(id)    ON DELETE RESTRICT,
  gross_paise          BIGINT NOT NULL CHECK (gross_paise > 0),
  fee_paise            BIGINT NOT NULL DEFAULT 0 CHECK (fee_paise >= 0),
  net_paise            BIGINT NOT NULL CHECK (net_paise > 0),
  status               payout_status NOT NULL DEFAULT 'pending',
  razorpay_transfer_id TEXT,
  failure_reason       TEXT,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  paid_at              TIMESTAMPTZ,
  -- One payout per booking; the safeguard against paying a seller twice.
  CONSTRAINT uq_payout_booking UNIQUE (booking_id)
);

CREATE INDEX IF NOT EXISTS idx_payouts_seller ON payouts(seller_id);
CREATE INDEX IF NOT EXISTS idx_payouts_status ON payouts(status);

-- ── REFUNDS ───────────────────────────────────────────────────────────────────

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'refund_status') THEN
    CREATE TYPE refund_status AS ENUM ('pending', 'processed', 'failed');
  END IF;
END
$$;

CREATE TABLE IF NOT EXISTS refunds (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  booking_id         UUID NOT NULL REFERENCES bookings(id) ON DELETE RESTRICT,
  amount_paise       BIGINT NOT NULL CHECK (amount_paise > 0),
  reason             TEXT NOT NULL,
  status             refund_status NOT NULL DEFAULT 'pending',
  razorpay_refund_id TEXT,
  failure_reason     TEXT,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  processed_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_refunds_booking ON refunds(booking_id);
CREATE INDEX IF NOT EXISTS idx_refunds_status  ON refunds(status);

CREATE UNIQUE INDEX IF NOT EXISTS uq_refunds_razorpay_id
  ON refunds (razorpay_refund_id) WHERE razorpay_refund_id IS NOT NULL;

-- ── SELLER PAYOUT DETAILS ─────────────────────────────────────────────────────
-- Razorpay Route linked account per seller. A seller who cannot be paid should
-- not be able to list, so listing creation will gate on this in Phase 2.2.

ALTER TABLE users
  ADD COLUMN IF NOT EXISTS razorpay_linked_account_id TEXT,
  ADD COLUMN IF NOT EXISTS kyc_status TEXT NOT NULL DEFAULT 'none',
  ADD COLUMN IF NOT EXISTS payout_hold BOOLEAN NOT NULL DEFAULT FALSE;

-- Service-key only; never exposed to the anon key.
ALTER TABLE ledger_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE payouts        ENABLE ROW LEVEL SECURITY;
ALTER TABLE refunds        ENABLE ROW LEVEL SECURITY;
