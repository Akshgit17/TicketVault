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
