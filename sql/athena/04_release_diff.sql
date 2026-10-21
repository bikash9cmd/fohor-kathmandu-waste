-- What changed in the facility registry between releases. 'rekeyed' means Overture gave
-- the same OpenStreetMap feature a new id; it is not a closure.
SELECT release, change, count(*) AS facilities
FROM fohor.facility_changes
WHERE release IN ('2026-09-23.0', '2026-09-23.1')
GROUP BY release, change
ORDER BY release, change;
