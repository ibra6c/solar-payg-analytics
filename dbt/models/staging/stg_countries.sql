select
    country_code,
    country_name,
    currency_code
from {{ source('raw', 'countries') }}
