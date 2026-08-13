-- Which migrations are actually applied?
--
-- There is no migrations table in this project (schema.sql is run by hand), so
-- "did that run?" has been answered by guesswork. This probes for a distinctive
-- artifact of each migration and reports APPLIED / MISSING.
--
-- Read-only. Safe to run any number of times.
--
-- Run this FIRST whenever something behaves as though a column does not exist.

WITH checks(seq, migration, artifact, present) AS (
  VALUES
    (1, '001_payment_integrity', 'unique index on bookings.razorpay_payment_id',
        (SELECT to_regclass('public.uq_bookings_payment_id') IS NOT NULL
             OR EXISTS (SELECT 1 FROM pg_indexes
                        WHERE tablename = 'bookings'
                          AND indexdef ILIKE '%razorpay_payment_id%'
                          AND indexdef ILIKE '%UNIQUE%'))),

    (2, '002_webhook_events', 'table webhook_events',
        (SELECT to_regclass('public.webhook_events') IS NOT NULL)),

    (3, '003_ledger', 'table ledger_entries',
        (SELECT to_regclass('public.ledger_entries') IS NOT NULL)),

    (4, '004_seller_payout_accounts', 'users.razorpay_linked_account_id',
        (SELECT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'users'
                          AND column_name = 'razorpay_linked_account_id'))),

    (5, '005_fulfillment', 'events.transfer_supported',
        (SELECT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'events'
                          AND column_name = 'transfer_supported'))),

    (6, '006_admin_and_event_requests', 'users.is_admin + event_requests',
        (SELECT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'users' AND column_name = 'is_admin')
            AND to_regclass('public.event_requests') IS NOT NULL)),

    (7, '007_city_dedupe', 'no duplicate Bangalore/Bengaluru',
        (SELECT NOT (EXISTS (SELECT 1 FROM cities WHERE name = 'Bangalore')
                 AND EXISTS (SELECT 1 FROM cities WHERE name = 'Bengaluru')))),

    (8, '008_prune_empty_cities', 'every city has at least one event',
        (SELECT NOT EXISTS (
           SELECT 1 FROM cities c
           WHERE NOT EXISTS (SELECT 1 FROM events e WHERE e.city_id = c.id)))),

    (9, '009_enable_transfer', 'all events transfer_supported = TRUE',
        (SELECT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'events' AND column_name = 'transfer_supported')
            AND NOT EXISTS (SELECT 1 FROM events WHERE transfer_supported IS NOT TRUE))),

    (10, '010_deposit_lifecycle', 'listings.deposit_returned_at',
        (SELECT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'listings'
                          AND column_name = 'deposit_returned_at'))),

    (11, '011_pricing', 'events.popularity_tier + pricing_recommendations',
        (SELECT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'events' AND column_name = 'popularity_tier')
            AND to_regclass('public.pricing_recommendations') IS NOT NULL)),

    -- Inverted on purpose: this migration REMOVES a column, so it is applied
    -- when the column is gone rather than when it is present.
    (12, '012_drop_generated_listing_fee', 'listings.listing_fee is gone',
        (SELECT NOT EXISTS (SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'listings'
                              AND column_name = 'listing_fee')))
)
SELECT
  migration,
  CASE WHEN present THEN 'APPLIED' ELSE '>>> MISSING <<<' END AS status,
  artifact
FROM checks
ORDER BY seq;
