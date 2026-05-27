-- TicketVault v2 — Complete Schema 
-- Run schema.sql first, then seed.sql

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- CITIES
CREATE TABLE IF NOT EXISTS cities (
  id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name      TEXT NOT NULL UNIQUE,
  slug      TEXT NOT NULL UNIQUE,
  is_active BOOLEAN NOT NULL DEFAULT TRUE
);

-- USERS
CREATE TABLE IF NOT EXISTS users (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  clerk_id   TEXT NOT NULL UNIQUE,
  name       TEXT NOT NULL,
  email      TEXT NOT NULL UNIQUE,
  phone      TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- EVENTS
CREATE TABLE IF NOT EXISTS events (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title      TEXT NOT NULL,
  venue      TEXT NOT NULL,
  city_id    UUID NOT NULL REFERENCES cities(id) ON DELETE RESTRICT,
  date       TIMESTAMPTZ NOT NULL,
  image_url  TEXT,
  source     TEXT DEFAULT 'manual',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_event UNIQUE (title, city_id, date)
);

CREATE INDEX IF NOT EXISTS idx_events_city ON events(city_id);
CREATE INDEX IF NOT EXISTS idx_events_date ON events(date);

-- LISTINGS  (tickets being sold by users)
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'listing_status') THEN
    CREATE TYPE listing_status AS ENUM (
      'pending_fee', 'active', 'locked', 'sold', 'cancelled'
    );
  END IF;
END
$$;

CREATE TABLE IF NOT EXISTS listings (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id       UUID NOT NULL REFERENCES events(id) ON DELETE RESTRICT,
  seller_id      UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  city_id        UUID NOT NULL REFERENCES cities(id) ON DELETE RESTRICT,
  price          NUMERIC(10,2) NOT NULL CHECK (price > 0),
  original_price NUMERIC(10,2) NOT NULL CHECK (original_price > 0),
  quantity       INT NOT NULL DEFAULT 1 CHECK (quantity > 0),
  listing_fee    NUMERIC(10,2) GENERATED ALWAYS AS (ROUND(price * 0.20, 2)) STORED,
  status         listing_status NOT NULL DEFAULT 'active',
  locked_by      UUID REFERENCES users(id),
  lock_expiry    TIMESTAMPTZ,
  qr_image_url   TEXT,
  qr_fingerprint          TEXT UNIQUE,
  fee_razorpay_order_id   TEXT,
  fee_razorpay_payment_id TEXT,
  created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_listings_event  ON listings(event_id);
CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(status);
CREATE INDEX IF NOT EXISTS idx_listings_city   ON listings(city_id);
CREATE INDEX IF NOT EXISTS idx_listings_seller ON listings(seller_id);

-- BOOKINGS  (completed purchases)
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'payment_status') THEN
    CREATE TYPE payment_status AS ENUM (
      'pending', 'paid', 'failed', 'refunded'
    );
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'confirmation_status') THEN
    CREATE TYPE confirmation_status AS ENUM (
      'pending', 'confirmed', 'auto_confirmed', 'disputed'
    );
  END IF;
END
$$;

CREATE TABLE IF NOT EXISTS bookings (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id               UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  listing_id            UUID NOT NULL REFERENCES listings(id) ON DELETE RESTRICT,
  quantity              INT NOT NULL DEFAULT 1,
  total_price           NUMERIC(10,2) NOT NULL,
  payment_status        payment_status NOT NULL DEFAULT 'pending',
  razorpay_order_id     TEXT,
  razorpay_payment_id   TEXT,
  confirmation_status   confirmation_status NOT NULL DEFAULT 'pending',
  confirmation_deadline TIMESTAMPTZ,
  buyer_name            TEXT,
  buyer_email           TEXT,
  buyer_phone           TEXT,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bookings_user    ON bookings(user_id);
CREATE INDEX IF NOT EXISTS idx_bookings_listing ON bookings(listing_id);
CREATE INDEX IF NOT EXISTS idx_bookings_status  ON bookings(payment_status, confirmation_status);

-- RLS
ALTER TABLE users     ENABLE ROW LEVEL SECURITY;
ALTER TABLE listings  ENABLE ROW LEVEL SECURITY;
ALTER TABLE bookings  ENABLE ROW LEVEL SECURITY;

-- Public reads (anon key used by SSR home page)
CREATE POLICY "Public read events"  ON events  FOR SELECT USING (true);
CREATE POLICY "Public read cities"  ON cities  FOR SELECT USING (true);
CREATE POLICY "Public read listings" ON listings FOR SELECT USING (true);
