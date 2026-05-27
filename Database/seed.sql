-- TicketVault — Seed Data (Cities + Sample Events)
-- Run AFTER schema.sql

-- CITIES
INSERT INTO cities (name, slug) VALUES
  ('Mumbai',     'mumbai'),
  ('New Delhi',  'new-delhi'),
  ('Bangalore',  'bangalore'),
  ('Bengaluru',  'bengaluru'),
  ('Hyderabad',  'hyderabad'),
  ('Chennai',    'chennai'),
  ('Kolkata',    'kolkata'),
  ('Pune',       'pune'),
  ('Ahmedabad',  'ahmedabad'),
  ('Jaipur',     'jaipur'),
  ('Lucknow',    'lucknow'),
  ('Kochi',      'kochi'),
  ('Chandigarh', 'chandigarh'),
  ('Goa',        'goa'),
  ('Surat',      'surat'),
  ('Indore',     'indore')
ON CONFLICT (name) DO NOTHING;

-- REPLACE ALL EXISTING CONCERT EVENTS
-- NOTE: We clear dependent marketplace data first due FK constraints.
DELETE FROM bookings
WHERE listing_id IN (
  SELECT id FROM listings WHERE event_id IN (SELECT id FROM events)
);
DELETE FROM listings
WHERE event_id IN (SELECT id FROM events);
DELETE FROM events;

-- CONCERT EVENTS
INSERT INTO events (title, venue, city_id, date, image_url, source)
VALUES
  (
    'Armaan Malik Live in Pune',
    'Mahalaxmi Lawns',
    (SELECT id FROM cities WHERE name = 'Pune'),
    '2026-08-11 19:00:00+05:30',
    'https://xnrolhgbaczqvbbrfcvd.supabase.co/storage/v1/object/public/event-images/Armaan.jpg',
    'manual'
  ),
  (
    'Gorillaz – The Mountain Tour (India)',
    'Jio World Garden',
    (SELECT id FROM cities WHERE name = 'Mumbai'),
    '2027-01-18 19:30:00+05:30',
    'https://xnrolhgbaczqvbbrfcvd.supabase.co/storage/v1/object/public/event-images/Gorillaz.jpg',
    'manual'
  ),
  (
    'Shaam-E-Mehfil with Papon',
    'Brilliant Convention Centre',
    (SELECT id FROM cities WHERE name = 'Indore'),
    '2026-06-28 18:30:00+05:30',
    'https://xnrolhgbaczqvbbrfcvd.supabase.co/storage/v1/object/public/event-images/Papon.jpg',
    'manual'
  ),
  (
    'Ye Live in India',
    'Jawaharlal Nehru Stadium',
    (SELECT id FROM cities WHERE name = 'New Delhi'),
    '2026-07-29 20:00:00+05:30',
    'https://xnrolhgbaczqvbbrfcvd.supabase.co/storage/v1/object/public/event-images/Ye.jpg',
    'manual'
  ),
  (
    'Raag-On Tour | Shankar-Ehsaan-Loy Live in Bengaluru',
    'Bangalore Palace',
    (SELECT id FROM cities WHERE name = 'Bengaluru'),
    '2026-07-22 19:00:00+05:30',
    'https://xnrolhgbaczqvbbrfcvd.supabase.co/storage/v1/object/public/event-images/Shankar-Ehsaan-Loy.jpg',
    'manual'
  )
ON CONFLICT (title, city_id, date) DO NOTHING;

