-- One row per property per month: what we expected to collect and what came in.
with leases as (
    select l.lease_id, u.property_id, l.monthly_rent
    from {{ ref('stg_leases') }} l
    join {{ ref('stg_units') }} u using (unit_id)
    where l.status = 'active'
    qualify row_number() over (partition by l.lease_id order by l.start_date) = 1
),
paid as (
    select l.property_id, p.rent_month, sum(p.amount) as collected, count(*) as payments
    from {{ ref('stg_rent_payments') }} p
    join leases l using (lease_id)
    group by all
)
select
    d.property_id,
    d.property_name,
    paid.rent_month,
    d.unit_count,
    count(leases.lease_id)                                  as occupied_units,
    round(count(leases.lease_id) / d.unit_count, 3)         as occupancy_rate,
    sum(leases.monthly_rent)                                as expected_rent,
    any_value(paid.collected)                               as collected_rent,
    round(any_value(paid.collected) / sum(leases.monthly_rent), 3) as collection_rate
from {{ ref('dim_property') }} d
left join leases using (property_id)
left join paid using (property_id)
group by d.property_id, d.property_name, paid.rent_month, d.unit_count
