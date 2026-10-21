-- How far people live from a mapped recycling drop-off (kabadi, Recyclo kiosk, sorting
-- point). "Mapped" matters: this measures OpenStreetMap and Overture's knowledge as much
-- as the ground, and data_gaps says where the map is thin.
select
    p.gers_id,
    p.name_en,
    p.district,
    p.population,
    coalesce(f.drop_offs, 0)                                                  as mapped_drop_offs,
    round(a.nearest_drop_off_m_median, 0)                                     as median_distance_m,
    round(a.share_within_500m, 3)                                             as share_within_500m,
    round(a.share_within_1000m, 3)                                            as share_within_1km,
    round(a.share_within_2000m, 3)                                            as share_within_2km,
    round(p.population * (1 - a.share_within_2000m), -2)                      as people_beyond_2km
from population p
left join access a using (gers_id)
left join (select gers_id_lg as gers_id, count(*) as drop_offs from facilities
           where kind = 'drop_off' and active group by 1) f using (gers_id)
order by people_beyond_2km desc
