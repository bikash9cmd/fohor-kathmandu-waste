-- Where the open map is thinnest, so nobody reads an empty map as an empty city.
select
    p.name_en,
    p.population,
    count(f.kind) filter (where f.kind = 'drop_off' and f.active)            as drop_offs,
    count(f.kind) filter (where f.kind = 'bin' and f.active)                 as public_bins,
    count(f.kind) filter (where f.kind = 'collector' and f.active)           as collectors,
    round(p.population / nullif(count(f.kind) filter (where f.kind = 'drop_off' and f.active), 0), -2)
                                                                              as people_per_drop_off
from population p
left join facilities f on f.gers_id_lg = p.gers_id
group by p.name_en, p.population
order by drop_offs, p.population desc
