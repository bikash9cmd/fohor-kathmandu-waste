-- What a one-week blockade of Bancharedanda leaves on the streets, largest first.
SELECT name_en, backlog_tonnes, organic_tonnes, truckloads, days_to_clear_after_reopening
FROM fohor.blockade_backlog
WHERE release = '2026-09-23.1' AND days_blocked = 7
ORDER BY backlog_tonnes DESC;
