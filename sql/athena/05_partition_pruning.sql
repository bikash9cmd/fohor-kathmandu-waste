-- Partition projection with an injected release: the WHERE clause is required, and
-- Athena reads exactly one prefix. Compare "Data scanned" with and without it removed
-- (without it, the query fails rather than scanning every release).
SELECT count(*) FROM fohor.facility_registry WHERE release = '2026-09-23.1';
