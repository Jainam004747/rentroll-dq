select
    property_id::varchar          as property_id,
    rent_month::varchar           as rent_month,
    gl_rent_total::decimal(14, 2) as gl_rent_total
from {{ source('landing', 'gl_rent_control') }}
