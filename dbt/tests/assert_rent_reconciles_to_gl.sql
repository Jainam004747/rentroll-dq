-- Payments received per property and month must match the total finance posted to the GL.
-- Any row returned is a reconciliation break.
{{ config(severity = 'error', tags = ['reconciliation'], meta = {'object': 'stg_rent_payments'}) }}

with paid as (
    select u.property_id, p.rent_month, sum(p.amount) as paid_total
    from {{ ref('stg_rent_payments') }} p
    join {{ ref('stg_leases') }} l using (lease_id)
    join {{ ref('stg_units') }} u using (unit_id)
    group by all
)
select
    g.property_id,
    g.rent_month,
    g.gl_rent_total,
    coalesce(paid.paid_total, 0)                   as paid_total,
    g.gl_rent_total - coalesce(paid.paid_total, 0) as difference
from {{ ref('stg_gl_rent_control') }} g
left join paid using (property_id, rent_month)
where abs(g.gl_rent_total - coalesce(paid.paid_total, 0)) > 0.01
