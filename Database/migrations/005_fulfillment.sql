-- 005_fulfillment.sql
-- Phase 3.1 — transfer-based fulfilment.
--
-- Replaces "seller uploads a QR image, buyer receives a copy" with "seller
-- reassigns the ticket inside BookMyShow/District, buyer confirms it landed".
-- The issuer transfer is single-use and irreversible, so the seller loses
-- access — which is the only thing that actually solves double-spend.
--
-- TicketVault cannot execute the transfer (no public API exists). It
-- orchestrates and verifies a manual one. Hence a per-booking SLA and a
-- buyer-attested confirmation step.
--
-- NOTE: `transfer_supported` is NULL by default — meaning "unknown", not
-- "no". Phase 0.1 validation fills it in per event. Nothing routes down the
-- transfer path until an event is explicitly marked TRUE.

-- ── EVENT-LEVEL TRANSFER CAPABILITY ───────────────────────────────────────────

ALTER TABLE events
  ADD COLUMN IF NOT EXISTS transfer_supported       BOOLEAN,
  ADD COLUMN IF NOT EXISTS transfer_window_opens_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS transfer_notes           TEXT;

CREATE INDEX IF NOT EXISTS idx_events_transfer ON events(transfer_supported);

-- ── BOOKING FULFILMENT STATE ──────────────────────────────────────────────────

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'fulfillment_status') THEN
    CREATE TYPE fulfillment_status AS ENUM (
      'not_started',        -- paid, fulfilment not yet applicable
      'awaiting_transfer',  -- seller must transfer; SLA clock running
      'transfer_initiated', -- seller says sent, proof attached
      'transfer_confirmed', -- BUYER confirmed it arrived — the real verification
      'released',           -- escrow released to the seller
      'failed'              -- SLA breached or dispute upheld; refunded
    );
  END IF;
END
$$;

ALTER TABLE bookings
  ADD COLUMN IF NOT EXISTS fulfillment_status    fulfillment_status NOT NULL DEFAULT 'not_started',
  ADD COLUMN IF NOT EXISTS transfer_deadline     TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS transfer_initiated_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS transfer_confirmed_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS transfer_proof_url    TEXT,
  -- The seller needs this to perform the transfer. Collected with explicit
  -- consent because it is disclosed to another user.
  ADD COLUMN IF NOT EXISTS buyer_platform_mobile TEXT,
  ADD COLUMN IF NOT EXISTS mobile_consent_at     TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS escrow_release_at     TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_bookings_fulfillment ON bookings(fulfillment_status);
CREATE INDEX IF NOT EXISTS idx_bookings_transfer_deadline
  ON bookings(transfer_deadline) WHERE fulfillment_status = 'awaiting_transfer';
CREATE INDEX IF NOT EXISTS idx_bookings_escrow_release
  ON bookings(escrow_release_at) WHERE fulfillment_status = 'transfer_confirmed';

-- ── AUDIT TRAIL ───────────────────────────────────────────────────────────────
-- Every state transition, appended. Disputes are argued from this table.

CREATE TABLE IF NOT EXISTS booking_events (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  booking_id  UUID NOT NULL REFERENCES bookings(id) ON DELETE RESTRICT,
  from_status TEXT,
  to_status   TEXT NOT NULL,
  actor       TEXT NOT NULL,          -- 'buyer' | 'seller' | 'system' | 'admin'
  actor_id    UUID REFERENCES users(id),
  reason      TEXT,
  metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_booking_events_booking ON booking_events(booking_id);

CREATE OR REPLACE FUNCTION booking_events_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'booking_events is append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_booking_events_append_only ON booking_events;
CREATE TRIGGER trg_booking_events_append_only
  BEFORE UPDATE OR DELETE ON booking_events
  FOR EACH ROW EXECUTE FUNCTION booking_events_append_only();

-- ── V1 SCOPE CONSTRAINTS ──────────────────────────────────────────────────────
--
-- Added NOT VALID: enforced for new and updated rows, but existing rows are not
-- checked, so the migration cannot fail on seed data. Clean the data, then run
--   ALTER TABLE listings VALIDATE CONSTRAINT chk_listing_quantity_one;
-- to enforce retroactively.

ALTER TABLE listings DROP CONSTRAINT IF EXISTS chk_listing_quantity_one;
ALTER TABLE listings
  ADD CONSTRAINT chk_listing_quantity_one CHECK (quantity = 1) NOT VALID;

-- Price cap — the TicketSwap-style trust guarantee, enforced in the database
-- rather than only in application code.
ALTER TABLE listings DROP CONSTRAINT IF EXISTS chk_listing_price_cap;
ALTER TABLE listings
  ADD CONSTRAINT chk_listing_price_cap
  CHECK (price <= original_price * 1.20) NOT VALID;

ALTER TABLE booking_events ENABLE ROW LEVEL SECURITY;
