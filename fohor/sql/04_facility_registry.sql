-- Every waste facility we know of, with where it came from and when we first saw it.
select
    f.facility_key,
    f.gers_id,
    f.name,
    f.kind,
    f.active,
    f.review,
    f.duplicate_of,
    f.evidence,
    f.dataset,
    f.source_record,
    round(f.confidence, 2)                                                    as confidence,
    l.name_en                                                                 as local_gov,
    round(f.lon, 6)                                                           as lon,
    round(f.lat, 6)                                                           as lat,
    h.first_seen_release,
    h.last_seen_release
from facilities f
left join population l on l.gers_id = f.gers_id_lg
left join facility_history h on h.facility_key = f.facility_key
order by f.kind, l.name_en, f.name
