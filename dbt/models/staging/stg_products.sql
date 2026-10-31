select
    product_id,
    product_name,
    category                as product_category,
    deposit_usd,
    daily_rate_usd,
    term_days,
    deposit_usd + daily_rate_usd * term_days as list_price_usd
from {{ source('raw', 'products') }}
