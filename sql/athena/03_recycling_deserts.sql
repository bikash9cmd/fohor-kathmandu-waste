-- People more than 2 km from any mapped recycling drop-off. Read with data_gaps: a zero
-- here can be a mapping gap as much as a missing kabadi.
SELECT a.name_en, a.population, a.mapped_drop_offs, a.median_distance_m, a.people_beyond_2km
FROM fohor.drop_off_access a
WHERE a.release = '2026-09-23.1'
ORDER BY a.people_beyond_2km DESC;
