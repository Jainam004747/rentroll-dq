select
    property_id::varchar as property_id,
    name                 as property_name,
    city,
    asset_type
from {{ source('landing', 'properties') }}
