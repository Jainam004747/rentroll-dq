select
    unit_id::varchar     as unit_id,
    property_id::varchar as property_id,
    sq_ft::integer       as sq_ft
from {{ source('landing', 'units') }}
