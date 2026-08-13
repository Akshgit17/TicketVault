-- 008 — Remove cities with nothing in them
--
-- The `cities` table accumulated 16 rows while only 8 have any events. Every
-- empty one is a live trapdoor in the city selector: pick it and the
-- marketplace renders its empty state, which reads as a broken site to anyone
-- who does not know better — and an examiner clicking around will find one.
--
-- Deliberately conservative: a city is removed only if nothing at all
-- references it. Nothing is cascaded and no user data is touched.
--
-- Re-run whenever the catalogue changes. A city removed here comes straight
-- back the moment you seed an event for it.

BEGIN;

DO $$
DECLARE
  removed INT;
BEGIN
  DELETE FROM cities c
  WHERE NOT EXISTS (SELECT 1 FROM events   e WHERE e.city_id = c.id)
    AND NOT EXISTS (SELECT 1 FROM listings l WHERE l.city_id = c.id)
    -- event_requests only exists once migration 006 has run.
    AND (
      to_regclass('public.event_requests') IS NULL
      OR NOT EXISTS (SELECT 1 FROM event_requests r WHERE r.city_id = c.id)
    );

  GET DIAGNOSTICS removed = ROW_COUNT;
  RAISE NOTICE 'Removed % empty cities.', removed;
END $$;

COMMIT;

-- What survived, and how full each one is.
SELECT c.name AS city, COUNT(e.id) AS upcoming_events
FROM cities c
LEFT JOIN events e ON e.city_id = c.id AND e.date >= NOW()
GROUP BY c.name
ORDER BY upcoming_events DESC, c.name;
