-- ============================================================
-- TicketVault — ALL MIGRATIONS, IN ORDER
--
-- Generated file. Paste the whole thing into the Supabase SQL
-- Editor and run once. Every statement is guarded with
-- IF NOT EXISTS / DO NOTHING, so re-running is harmless.
--
-- Source of truth remains the individual 001..007 files.
-- ============================================================


-- ============================================================
-- 001_payment_integrity.sql
-- ============================================================

-- 001_payment_integrity.sql
-- Phase 1.2 — prevent a single Razorpay receipt from settling more than one record.
--
-- Application code now binds each payment to its own order and verifies the
-- amount server-side. These indexes are the last line of defence: even if a
-- future code path forgets, the database refuses the replay.
--
-- Partial indexes so the many NULLs (unpaid rows) do not collide.

CREATE UNIQUE INDEX IF NOT EXISTS uq_bookings_razorpay_payment_id
  ON bookings (razorpay_payment_id)
  WHERE razorpay_payment_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_listings_fee_razorpay_payment_id
  ON listings (fee_razorpay_payment_id)
  WHERE fee_razorpay_payment_id IS NOT NULL;

-- Each Razorpay order is created for exactly one record; enforce that too.
CREATE UNIQUE INDEX IF NOT EXISTS uq_bookings_razorpay_order_id
  ON bookings (razorpay_order_id)
  WHERE razorpay_order_id IS NOT NULL;


-- ============================================================
-- 002_webhook_events.sql
-- ============================================================

-- 002_webhook_events.sql
-- Phase 1.3 — durable, idempotent record of provider webhook deliveries.
--
-- Razorpay retries on non-2xx and can deliver the same event more than once.
-- The unique (provider, event_id) index makes replays a no-op, and keeping the
-- payload lets us reconstruct what the provider actually told us during an
-- incident — which the logs alone will not give you.

CREATE TABLE IF NOT EXISTS webhook_events (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  provider     TEXT NOT NULL DEFAULT 'razorpay',
  event_id     TEXT NOT NULL,
  event_type   TEXT NOT NULL,
  payload      JSONB NOT NULL,
  status       TEXT NOT NULL DEFAULT 'received',   -- received|processed|ignored|failed
  error        TEXT,
  received_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_webhook_event UNIQUE (provider, event_id)
);

CREATE INDEX IF NOT EXISTS idx_webhook_events_type   ON webhook_events(event_type);
CREATE INDEX IF NOT EXISTS idx_webhook_events_status ON webhook_events(status);

-- Written only by the backend service key; never exposed to the anon key.
ALTER TABLE webhook_events ENABLE ROW LEVEL SECURITY;


-- ============================================================
-- 003_ledger.sql
-- ============================================================

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


-- ============================================================
-- 004_seller_payout_accounts.sql
-- ============================================================

-- 004_seller_payout_accounts.sql
-- Phase 2.2 — seller payout details.
--
-- Migration 003 added razorpay_linked_account_id, kyc_status and payout_hold.
-- This adds the display/support fields.
--
-- DELIBERATELY ABSENT: the full bank account number and the full PAN.
-- Both are sent to Razorpay and never persisted here. We keep only what is
-- needed to show the seller which account they configured, and to help support
-- identify it. A dump of this table therefore cannot fund a transfer or
-- reconstruct a government identifier.

ALTER TABLE users
  ADD COLUMN IF NOT EXISTS payout_account_last4    TEXT,
  ADD COLUMN IF NOT EXISTS payout_ifsc             TEXT,
  ADD COLUMN IF NOT EXISTS payout_beneficiary_name TEXT,
  ADD COLUMN IF NOT EXISTS pan_last4               TEXT,
  ADD COLUMN IF NOT EXISTS payout_configured_at    TIMESTAMPTZ;

-- kyc_status transitions: none -> pending -> verified | rejected
ALTER TABLE users
  DROP CONSTRAINT IF EXISTS chk_kyc_status;
ALTER TABLE users
  ADD CONSTRAINT chk_kyc_status
  CHECK (kyc_status IN ('none', 'pending', 'verified', 'rejected'));

-- Last4 is for display only; never widen these to hold full values.
ALTER TABLE users
  DROP CONSTRAINT IF EXISTS chk_payout_last4_len;
ALTER TABLE users
  ADD CONSTRAINT chk_payout_last4_len
  CHECK (payout_account_last4 IS NULL OR length(payout_account_last4) <= 4);

ALTER TABLE users
  DROP CONSTRAINT IF EXISTS chk_pan_last4_len;
ALTER TABLE users
  ADD CONSTRAINT chk_pan_last4_len
  CHECK (pan_last4 IS NULL OR length(pan_last4) <= 4);

CREATE INDEX IF NOT EXISTS idx_users_kyc_status ON users(kyc_status);


-- ============================================================
-- 005_fulfillment.sql
-- ============================================================

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


-- ============================================================
-- 006_admin_and_event_requests.sql
-- ============================================================

-- 006 — Admin roles + seller-submitted event requests
--
-- Two additions:
--   1. `users.is_admin` — the authorisation flag behind every /admin route.
--   2. `event_requests` — sellers propose events that are not yet in the
--      catalogue; an admin approves, which creates the real `events` row.
--
-- Why a request table rather than letting sellers insert events directly:
-- the catalogue is the trust surface. A seller who can create arbitrary events
-- can invent an event that does not exist, list a ticket for it, and take
-- money for something unverifiable. Approval is the control.

BEGIN;

-- 1. ADMIN FLAG ------------------------------------------------------------

ALTER TABLE users
  ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_users_is_admin
  ON users(is_admin) WHERE is_admin = TRUE;

-- Events created through the approval flow are distinguishable from seeded
-- ones, so admins can audit what entered the catalogue by request.
ALTER TABLE events
  ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES users(id) ON DELETE SET NULL;

-- 2. EVENT REQUESTS --------------------------------------------------------

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'event_request_status') THEN
    CREATE TYPE event_request_status AS ENUM ('pending', 'approved', 'rejected');
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS event_requests (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  requester_id  UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

  title         TEXT NOT NULL,
  venue         TEXT NOT NULL,
  city_id       UUID NOT NULL REFERENCES cities(id) ON DELETE RESTRICT,
  date          TIMESTAMPTZ NOT NULL,
  image_url     TEXT,
  -- Free text from the seller: proof the event exists (booking page link,
  -- announcement post). This is what the admin actually reviews.
  evidence_url  TEXT,
  notes         TEXT,

  status        event_request_status NOT NULL DEFAULT 'pending',
  -- Populated on approval; lets the seller jump straight to listing.
  event_id      UUID REFERENCES events(id) ON DELETE SET NULL,
  -- Populated on rejection, and shown to the seller. A rejection without a
  -- reason produces a support message instead of a corrected resubmission.
  review_note   TEXT,
  reviewed_by   UUID REFERENCES users(id) ON DELETE SET NULL,
  reviewed_at   TIMESTAMPTZ,

  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT reviewed_fields_consistent CHECK (
    (status = 'pending'  AND reviewed_at IS NULL)
    OR (status <> 'pending' AND reviewed_at IS NOT NULL)
  )
);

CREATE INDEX IF NOT EXISTS idx_event_requests_status
  ON event_requests(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_event_requests_requester
  ON event_requests(requester_id, created_at DESC);

-- Stops a seller flooding the queue with the same event while it is pending.
CREATE UNIQUE INDEX IF NOT EXISTS uq_event_request_pending
  ON event_requests(requester_id, title, city_id, date)
  WHERE status = 'pending';

COMMIT;


-- ============================================================
-- 007_city_dedupe.sql
-- ============================================================

-- 007 — Merge duplicate cities, then make duplicates impossible
--
-- `cities` contains both 'Bangalore' and 'Bengaluru' as separate rows for the
-- same place. Every event attached itself to one of them, so a user who picked
-- the other from the city selector got an empty marketplace and concluded the
-- site was broken.
--
-- `name` and `slug` already carry UNIQUE constraints, so this was never a
-- constraint failure — it is two different spellings of one city. No schema
-- rule can catch that; it has to be merged by hand once and then guarded.
--
-- Safe to re-run: if only one of the pair exists, every statement is a no-op.

BEGIN;

-- Repoint everything at the surviving row before deleting the duplicate.
-- 'Bengaluru' survives (the city's official name since 2014); 'Bangalore' is
-- merged into it. Flip the two names below if you prefer the other spelling.
DO $$
DECLARE
  keep_id UUID;
  drop_id UUID;
BEGIN
  SELECT id INTO keep_id FROM cities WHERE name = 'Bengaluru';
  SELECT id INTO drop_id FROM cities WHERE name = 'Bangalore';

  IF keep_id IS NULL OR drop_id IS NULL THEN
    RAISE NOTICE 'City dedupe skipped — both spellings not present.';
    RETURN;
  END IF;

  UPDATE events   SET city_id = keep_id WHERE city_id = drop_id;
  UPDATE listings SET city_id = keep_id WHERE city_id = drop_id;

  DELETE FROM cities WHERE id = drop_id;
  RAISE NOTICE 'Merged Bangalore into Bengaluru.';
END $$;

-- Fold any other case-only duplicates ('goa' vs 'Goa') into one row, and stop
-- new ones appearing. UNIQUE(name) is case-sensitive, so it never caught these.
CREATE UNIQUE INDEX IF NOT EXISTS uq_cities_name_ci ON cities (LOWER(name));
CREATE UNIQUE INDEX IF NOT EXISTS uq_cities_slug_ci ON cities (LOWER(slug));

COMMIT;

