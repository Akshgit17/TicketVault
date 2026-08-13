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
