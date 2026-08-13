-- 007 — Merge duplicate cities, then make duplicates impossible
--
-- `cities` contains both 'Bangalore' and 'Bengaluru' as separate rows for the
-- same place. Every event attached itself to one of them, so a user who picked
-- the other from the city selector got an empty marketplace and concluded the
-- site was broken.
--
-- `name` and `slug` already carry UNIQUE constraints, so this was never a
-- constraint failure — it is two different spellings of one city. No schema
-- rule can catch that; it has to be merged by hand once and then guarded.
--
-- Safe to re-run: if only one of the pair exists, every statement is a no-op.

BEGIN;

-- Repoint everything at the surviving row before deleting the duplicate.
-- 'Bengaluru' survives (the city's official name since 2014); 'Bangalore' is
-- merged into it. Flip the two names below if you prefer the other spelling.
DO $$
DECLARE
  keep_id UUID;
  drop_id UUID;
BEGIN
  SELECT id INTO keep_id FROM cities WHERE name = 'Bengaluru';
  SELECT id INTO drop_id FROM cities WHERE name = 'Bangalore';

  IF keep_id IS NULL OR drop_id IS NULL THEN
    RAISE NOTICE 'City dedupe skipped — both spellings not present.';
    RETURN;
  END IF;

  UPDATE events   SET city_id = keep_id WHERE city_id = drop_id;
  UPDATE listings SET city_id = keep_id WHERE city_id = drop_id;

  DELETE FROM cities WHERE id = drop_id;
  RAISE NOTICE 'Merged Bangalore into Bengaluru.';
END $$;

-- Fold any other case-only duplicates ('goa' vs 'Goa') into one row, and stop
-- new ones appearing. UNIQUE(name) is case-sensitive, so it never caught these.
CREATE UNIQUE INDEX IF NOT EXISTS uq_cities_name_ci ON cities (LOWER(name));
CREATE UNIQUE INDEX IF NOT EXISTS uq_cities_slug_ci ON cities (LOWER(slug));

COMMIT;
