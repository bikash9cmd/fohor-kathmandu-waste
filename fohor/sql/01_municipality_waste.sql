-- One row per local government: people, tonnes sent to Bancharedanda, and the haul.
-- Tonnage is the reported landfill intake (1,400 t/day) shared by population. That
-- assumes the same kg per person everywhere, which is wrong in detail (the core makes
-- more commercial waste) and right in total; docs/DATA.md says why we accept it.
with tot as (select sum(population) as people, sum(hrsl_population) as hrsl_people from population)
select
    p.gers_id,
    p.name_en,
    p.district,
    p.population,
    p.population_source,
    round(p.population / tot.people, 4)                                       as population_share,
    round(getvariable('landfill_tpd') * p.population / tot.people, 1)         as tonnes_per_day,
    -- The same intake shared by HRSL, which follows building footprints. It puts more in
    -- the commercial core, closer to KMC's own 500-600 t/day; the truth is between the two.
    round(getvariable('landfill_tpd') * p.hrsl_population / tot.hrsl_people, 1) as tonnes_per_day_building_share,
    round(getvariable('adb_kg') * p.population / 1000.0, 1)                   as tonnes_per_day_at_adb_rate,
    round(1000.0 * getvariable('landfill_tpd') / tot.people, 3)               as implied_kg_per_person_day,
    round(h.haul_km_mean, 1)                                                  as haul_km_mean,
    round(h.haul_km_p10, 1)                                                   as haul_km_p10,
    round(h.haul_km_p90, 1)                                                   as haul_km_p90,
    round(getvariable('landfill_tpd') * p.population / tot.people / getvariable('t_per_truck'), 1) as truck_trips_per_day,
    round(2 * h.haul_km_mean * getvariable('landfill_tpd') * p.population / tot.people
          / getvariable('t_per_truck'), 0)                                    as truck_km_per_day,
    round(2 * h.haul_km_mean / getvariable('truck_kmh'), 1)                   as round_trip_hours
from population p
cross join tot
left join haul h using (gers_id)
order by tonnes_per_day desc
