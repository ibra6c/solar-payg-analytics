select
    customer_id,
    country_code,
    region,
    gender,
    age_band,
    occupation,
    registered_at
from {{ source('raw', 'customers') }}
