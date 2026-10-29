select
    p.property_id,
    p.property_name,
    p.city,
    p.asset_type,
    count(u.unit_id)  as unit_count,
    sum(u.sq_ft)      as total_sq_ft
from {{ ref('stg_properties') }} p
left join {{ ref('stg_units') }} u using (property_id)
group by all
