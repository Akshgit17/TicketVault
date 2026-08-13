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
