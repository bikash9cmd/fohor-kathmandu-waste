-- Truck-km per day by local government: where segregation or a nearer transfer point
-- would save the most driving.
SELECT name_en, tonnes_per_day, haul_km_mean, truck_trips_per_day, truck_km_per_day,
       round(100.0 * truck_km_per_day / sum(truck_km_per_day) OVER (), 1) AS pct_of_valley_truck_km
FROM fohor.municipality_waste
WHERE release = '2026-09-23.1'
ORDER BY truck_km_per_day DESC;
