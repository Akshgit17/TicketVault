-- TicketVault — Seed Data (Cities + Concert Catalogue)
-- Run AFTER schema.sql and the migrations in migrations/run_all.sql
--
-- ⚠️  DESTRUCTIVE. This deletes every booking, listing and event before
--     reseeding. That is deliberate — it is the "reset to a known good
--     state" script you run before rehearsing a demo — but do not run it
--     against data you want to keep.
--
-- Two things worth knowing about how this file works:
--
-- 1. Dates are RELATIVE (CURRENT_DATE + n days), not hardcoded. The previous
--    seed pinned absolute dates in 2026, so three of its five events had
--    already happened and the catalogue looked broken the moment the public
--    /events filter started excluding past shows. Relative dates mean this
--    file never expires.
--
-- 2. The catalogue is CONCENTRATED, not spread thin. Serving every city with
--    five events total meant most cities rendered empty. Eight cities with
--    real depth demos far better than sixteen with one show each.

-- ── CITIES ───────────────────────────────────────────────────────────────────
-- 'Bangalore' is deliberately absent: it duplicated 'Bengaluru' and split the
-- catalogue in two. See migrations/007_city_dedupe.sql, which merges any
-- existing rows and adds a case-insensitive unique index.

INSERT INTO cities (name, slug) VALUES
  ('Mumbai',     'mumbai'),
  ('New Delhi',  'new-delhi'),
  ('Bengaluru',  'bengaluru'),
  ('Hyderabad',  'hyderabad'),
  ('Pune',       'pune'),
  ('Chennai',    'chennai'),
  ('Kolkata',    'kolkata'),
  ('Goa',        'goa'),
  ('Ahmedabad',  'ahmedabad'),
  ('Jaipur',     'jaipur'),
  ('Kochi',      'kochi'),
  ('Chandigarh', 'chandigarh'),
  ('Indore',     'indore')
ON CONFLICT (name) DO NOTHING;


-- ── RESET ────────────────────────────────────────────────────────────────────
-- Deletion order matters, and it is not obvious.
--
-- After the migrations run, ledger_entries, payouts, refunds and
-- booking_events all reference bookings/listings with ON DELETE RESTRICT —
-- deliberately, because financial history must not be silently erasable. So a
-- plain `DELETE FROM listings` fails the moment anyone has actually bought
-- something. These have to be cleared first, deepest dependency outward.
--
-- DELETE cannot be used at all here: migration 003 puts a BEFORE UPDATE OR
-- DELETE trigger on ledger_entries that raises unconditionally, so financial
-- history is genuinely immutable. TRUNCATE is the escape hatch — row-level
-- triggers do not fire on it — and CASCADE works out the dependency order
-- itself. `users`, `seller_payout_accounts` and `webhook_events` are not
-- listed and are not reachable by cascade from these, so accounts survive a
-- reset.
--
-- to_regclass keeps this working before the migrations have been applied,
-- when most of these tables do not exist yet.

DO $$
DECLARE
  present TEXT[] := '{}';
  t       TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'events', 'listings', 'bookings',
    'booking_events',                     -- 005
    'ledger_entries', 'payouts', 'refunds' -- 003
  ] LOOP
    IF to_regclass('public.' || t) IS NOT NULL THEN
      present := present || quote_ident(t);
    END IF;
  END LOOP;

  IF array_length(present, 1) > 0 THEN
    EXECUTE 'TRUNCATE TABLE ' || array_to_string(present, ', ') || ' CASCADE';
  END IF;
END $$;


-- ── EVENTS ───────────────────────────────────────────────────────────────────
-- `days` is an offset from today, so every show is always upcoming.
--
-- NOTE ON IMAGES: only the five artists below have real poster art in Supabase
-- storage. Everything else uses one generic concert photo, so the grid has no
-- broken images — but before you demo, swapping in real posters is the single
-- highest-impact cosmetic change you can make to this project.

INSERT INTO events (title, venue, city_id, date, image_url, source)
SELECT
  v.title,
  v.venue,
  c.id,
  (CURRENT_DATE + (v.days * INTERVAL '1 day') + v.tod)::timestamptz,
  v.img,
  'manual'
FROM (VALUES
  -- Mumbai
  ('Gorillaz – The Mountain Tour (India)', 'Jio World Garden',            'Mumbai',    46,  TIME '19:30', 'https://xnrolhgbaczqvbbrfcvd.supabase.co/storage/v1/object/public/event-images/Gorillaz.jpg'),
  ('Arijit Singh — One Night Only',        'DY Patil Stadium',            'Mumbai',    12,  TIME '19:00', NULL),
  ('Lollapalooza India — Day 1',           'Mahalaxmi Racecourse',        'Mumbai',    68,  TIME '14:00', NULL),
  ('Lollapalooza India — Day 2',           'Mahalaxmi Racecourse',        'Mumbai',    69,  TIME '14:00', NULL),
  ('The Local Train — Aalas Ka Pedh Tour', 'Bal Gandharva Rang Mandir',   'Mumbai',    27,  TIME '20:00', NULL),
  ('Nucleya presents Bass Rani Reloaded',  'NSCI Dome',                   'Mumbai',    54,  TIME '21:00', NULL),

  -- New Delhi
  ('Ye Live in India',                     'Jawaharlal Nehru Stadium',    'New Delhi', 33,  TIME '20:00', 'https://xnrolhgbaczqvbbrfcvd.supabase.co/storage/v1/object/public/event-images/Ye.jpg'),
  ('Diljit Dosanjh — Dil-Luminati Tour',   'JLN Stadium',                 'New Delhi', 21,  TIME '19:00', NULL),
  ('Prateek Kuhad — Silhouettes Tour',     'Kamani Auditorium',           'New Delhi', 9,   TIME '19:30', NULL),
  ('Indian Ocean — 35 Years Live',         'Talkatora Stadium',           'New Delhi', 41,  TIME '18:30', NULL),
  ('Sunburn Arena ft. Alan Walker',        'Gate No.4, JLN Stadium',      'New Delhi', 58,  TIME '17:00', NULL),

  -- Bengaluru
  ('Raag-On Tour | Shankar-Ehsaan-Loy',    'Bangalore Palace',            'Bengaluru', 18,  TIME '19:00', 'https://xnrolhgbaczqvbbrfcvd.supabase.co/storage/v1/object/public/event-images/Shankar-Ehsaan-Loy.jpg'),
  ('Bengaluru Open Air — Metal Fest',      'Phoenix Marketcity Grounds',  'Bengaluru', 37,  TIME '15:00', NULL),
  ('When Chai Met Toast — Live',           'Phoenix Arena',               'Bengaluru', 7,   TIME '20:00', NULL),
  ('Raghu Dixit Project — Homecoming',     'Bangalore Palace Grounds',    'Bengaluru', 52,  TIME '18:00', NULL),
  ('Ritviz — Baaraat Tour',                'Manpho Convention Centre',    'Bengaluru', 25,  TIME '21:00', NULL),

  -- Hyderabad
  ('Anirudh Ravichander Live',             'GMC Balayogi Stadium',        'Hyderabad', 15,  TIME '18:30', NULL),
  ('Sunburn Reload — Hyderabad',           'Hitex Exhibition Centre',     'Hyderabad', 44,  TIME '17:00', NULL),
  ('Agam — Carnatic Progressive Rock',     'Shilpakala Vedika',           'Hyderabad', 29,  TIME '19:30', NULL),
  ('Karan Aujla — It Was All A Dream',     'Gachibowli Stadium',          'Hyderabad', 61,  TIME '19:00', NULL),

  -- Pune
  ('Armaan Malik Live in Pune',            'Mahalaxmi Lawns',             'Pune',      11,  TIME '19:00', 'https://xnrolhgbaczqvbbrfcvd.supabase.co/storage/v1/object/public/event-images/Armaan.jpg'),
  ('NH7 Weekender — Pune Edition',         'Laxmi Lawns',                 'Pune',      49,  TIME '13:00', NULL),
  ('Parvaaz — Live in Concert',            'Sky Lawns, Baner',            'Pune',      23,  TIME '20:00', NULL),
  ('Divine — Gully Gang Live',             'Mahalaxmi Lawns',             'Pune',      35,  TIME '19:30', NULL),

  -- Chennai
  ('A.R. Rahman — Marakuma Nenjam',        'YMCA Grounds, Nandanam',      'Chennai',   31,  TIME '18:00', NULL),
  ('Thaikkudam Bridge Live',               'Kamarajar Arangam',           'Chennai',   14,  TIME '19:30', NULL),
  ('Chennai Music Festival — Opening',     'Music Academy',               'Chennai',   56,  TIME '18:30', NULL),
  ('Sid Sriram — Sidharth Live',           'Nehru Indoor Stadium',        'Chennai',   40,  TIME '19:00', NULL),

  -- Kolkata
  ('Shaam-E-Mehfil with Papon',            'Nazrul Mancha',               'Kolkata',   19,  TIME '18:30', 'https://xnrolhgbaczqvbbrfcvd.supabase.co/storage/v1/object/public/event-images/Papon.jpg'),
  ('Fossils — Rock Nights',                'Netaji Indoor Stadium',       'Kolkata',   38,  TIME '19:00', NULL),
  ('Bickram Ghosh — Rhythmscape',          'Kala Mandir',                 'Kolkata',   26,  TIME '18:00', NULL),

  -- Goa
  ('Sunburn Festival Goa — Day 1',         'Vagator Hilltop',             'Goa',       63,  TIME '16:00', NULL),
  ('Sunburn Festival Goa — Day 2',         'Vagator Hilltop',             'Goa',       64,  TIME '16:00', NULL),
  ('Goa Sunsplash — Reggae Festival',      'Ashwem Beach',                'Goa',       30,  TIME '15:00', NULL),
  ('Hilltop New Year Sessions',            'Hilltop, Vagator',            'Goa',       72,  TIME '20:00', NULL)
) AS v(title, venue, city, days, tod, img)
JOIN cities c ON c.name = v.city
ON CONFLICT (title, city_id, date) DO NOTHING;


-- Generic artwork for every event without a real poster, so the grid never
-- shows an empty tile. Replace with actual posters before demoing.
UPDATE events
SET image_url = 'https://images.unsplash.com/photo-1470229722913-7c0e2dbbafd3?w=1200&q=70'
WHERE image_url IS NULL;


-- ── ENABLE TRANSFER ──────────────────────────────────────────────────────────
-- Without this every booking falls through to the legacy QR path and the
-- seller never gets a transfer task — the whole transfer flow is unreachable.
-- Migration 009 also sets this as the column default; repeated here so a reset
-- cannot silently undo it. Guarded because the column only exists after 005.

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name   = 'events'
      AND column_name  = 'transfer_supported'
  ) THEN
    UPDATE events SET transfer_supported = TRUE;
    RAISE NOTICE 'Transfer enabled for all events.';
  ELSE
    RAISE NOTICE 'Skipped: run migration 005 first.';
  END IF;
END $$;


-- ── SANITY CHECK ─────────────────────────────────────────────────────────────
-- Every city listed here should have a non-zero count, and every date should
-- be in the future. If a city shows 0, the marketplace will look broken for
-- anyone who selects it.

SELECT c.name AS city, COUNT(e.id) AS upcoming_events
FROM cities c
LEFT JOIN events e ON e.city_id = c.id AND e.date >= NOW()
GROUP BY c.name
ORDER BY upcoming_events DESC, c.name;
