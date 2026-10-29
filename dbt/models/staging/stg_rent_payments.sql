select
    payment_id::varchar     as payment_id,
    lease_id::varchar       as lease_id,
    paid_on::date           as paid_on,
    strftime(paid_on::date, '%Y-%m') as rent_month,
    amount::decimal(12, 2)  as amount
from {{ source('landing', 'rent_payments') }}
