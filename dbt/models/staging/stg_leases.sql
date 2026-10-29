select
    lease_id::varchar            as lease_id,
    nullif(unit_id::varchar, '') as unit_id,
    tenant,
    monthly_rent::decimal(12, 2) as monthly_rent,
    start_date::date             as start_date,
    end_date::date               as end_date,
    lower(status)                as status
from {{ source('landing', 'leases') }}
