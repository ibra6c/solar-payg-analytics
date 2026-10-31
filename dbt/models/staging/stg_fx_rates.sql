select
    country_code,
    currency_code,
    rate_month,
    local_per_usd,
    1.0 / local_per_usd as usd_per_local
from {{ source('raw', 'fx_rates') }}
