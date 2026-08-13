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
