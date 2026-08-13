-- 012 — Drop the generated listing_fee column
--
-- `listings.listing_fee` was declared as
--
--     NUMERIC(10,2) GENERATED ALWAYS AS (ROUND(price * 0.20, 2)) STORED
--
-- which hardcodes the deposit rate in the schema while app/config.py holds
-- LISTING_FEE_RATE for the same number. Two sources of truth for a value the
-- seller is charged: change the config and the column silently disagrees,
-- change the column and you need a migration to alter a rate that was supposed
-- to be configuration.
--
-- Nothing depends on it any more. Migration 010 added `deposit_paid_paise`,
-- which records what was ACTUALLY charged rather than what the current rate
-- would compute, and that distinction matters: a deposit must be returned at
-- the amount taken, not at today's rate. `deposits.deposit_paise()` already
-- prefers it and falls back to `price * LISTING_FEE_RATE`, so the generated
-- column is only reached for rows that predate 010.
--
-- Back-fill first, then drop, so nothing loses its recorded amount.

BEGIN;

-- Preserve what old rows were charged, for any that never got the explicit
-- field. Guarded on NULL so a real recorded amount is never overwritten by a
-- recomputation.
UPDATE listings
   SET deposit_paid_paise = ROUND(listing_fee * 100)
 WHERE deposit_paid_paise IS NULL
   AND listing_fee IS NOT NULL
   AND fee_razorpay_payment_id IS NOT NULL;   -- only where a deposit was really paid

ALTER TABLE listings DROP COLUMN IF EXISTS listing_fee;

COMMIT;

-- Should return zero rows: any listing that paid a deposit now records how much.
SELECT id, price, deposit_paid_paise
  FROM listings
 WHERE fee_razorpay_payment_id IS NOT NULL
   AND deposit_paid_paise IS NULL;
