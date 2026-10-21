-- If trucks cannot reach the landfill for N days, what piles up and how long does it
-- take to clear? Clearing assumes the fleet can surge to fleet_surge x its normal
-- daily trips once the road opens. That surge factor is an assumption (config.py).
with days as (select range as days_blocked from range(1, 31)),
lg as (
    select name_en, district, tonnes_per_day from municipality_waste
    union all
    select 'Kathmandu Valley (18 local governments)', 'all', getvariable('landfill_tpd')
)
select
    lg.name_en,
    lg.district,
    d.days_blocked,
    round(lg.tonnes_per_day * d.days_blocked, 0)                              as backlog_tonnes,
    round(lg.tonnes_per_day * d.days_blocked * getvariable('organic_share'), 0) as organic_tonnes,
    ceil(lg.tonnes_per_day * d.days_blocked / getvariable('t_per_truck'))       as truckloads,
    round(d.days_blocked / (getvariable('fleet_surge') - 1), 1)                as days_to_clear_after_reopening,
    round(d.days_blocked / 0.2, 1)                                             as days_to_clear_if_surge_120pct,
    round(d.days_blocked / 0.5, 1)                                             as days_to_clear_if_surge_150pct
from lg cross join days d
order by lg.name_en = 'Kathmandu Valley (18 local governments)' desc, lg.tonnes_per_day desc, d.days_blocked
