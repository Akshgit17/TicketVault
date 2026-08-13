-- 013 — Cancellation and postponement for events
--
-- Concerts get moved and called off, and until now the catalogue had no way to
-- say so. An admin could only edit rows by hand in the database, and a
-- cancelled show would keep selling tickets.
--
-- Two different situations, deliberately modelled differently:
--
--   POSTPONED  the date moves. The ticket is still valid: BookMyShow and
--              District honour tickets for a rescheduled show, so refunding
--              everyone automatically would be wrong and unwelcome. Record
--              where it moved from so buyers can see the change.
--
--   CANCELLED  the show is off. Nobody can deliver a ticket to it, so every
--              unreleased booking is refunded and every listing withdrawn.
--              Crucially the SELLER IS NOT AT FAULT, so deposits are RETURNED
--              rather than forfeited. Forfeiting here would punish sellers for
--              something a promoter did.

BEGIN;

ALTER TABLE events
  -- Nullable timestamp rather than a status enum: an event is cancelled or it
  -- is not, and "when" is worth keeping. Same shape as the deposit
  -- resolution columns, for consistency.
  ADD COLUMN IF NOT EXISTS cancelled_at        TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS cancellation_reason TEXT,
  -- The original date, kept when a show is rescheduled so the UI can say
  -- "moved from 11 August" rather than silently showing a different date.
  ADD COLUMN IF NOT EXISTS postponed_from      TIMESTAMPTZ;

-- Public browse filters on this constantly, so index the live rows only.
CREATE INDEX IF NOT EXISTS idx_events_live
  ON events(date)
  WHERE cancelled_at IS NULL;

COMMIT;

SELECT
  COUNT(*)                                   AS total_events,
  COUNT(*) FILTER (WHERE cancelled_at IS NOT NULL) AS cancelled,
  COUNT(*) FILTER (WHERE postponed_from IS NOT NULL) AS postponed
FROM events;
