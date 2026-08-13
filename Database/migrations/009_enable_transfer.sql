-- 009 — Enable issuer-side transfer for the whole catalogue
--
-- Migration 005 added `events.transfer_supported` with no default, so every
-- event sat at NULL. fulfillment.py treats NULL as "not transfer-enabled" and
-- routes the booking down the legacy QR path (see start_transfer_flow), which
-- means the seller never receives a transfer task and the entire transfer UI
-- is unreachable. A paid booking simply stops at not_started.
--
-- Per Decision 1 the transfer model *is* the fulfilment model, so the sensible
-- state is the opposite: enabled unless someone deliberately turns it off.
--
-- `transfer_window_opens_at` is deliberately left NULL. fulfillment.py reads
-- NULL as "the window is already open" and starts the SLA clock the moment
-- payment settles — which is what you want for a demo, and honest for a
-- catalogue where no real transfer window is being tracked.

BEGIN;

-- Existing rows.
UPDATE events SET transfer_supported = TRUE WHERE transfer_supported IS NOT TRUE;

-- New rows, including events created by the admin approval flow. Without this,
-- every approved event request would silently reintroduce the same trap.
ALTER TABLE events ALTER COLUMN transfer_supported SET DEFAULT TRUE;

COMMIT;

SELECT
  COUNT(*)                                        AS total_events,
  COUNT(*) FILTER (WHERE transfer_supported)      AS transfer_enabled,
  COUNT(*) FILTER (WHERE transfer_supported IS NOT TRUE) AS still_legacy
FROM events;
