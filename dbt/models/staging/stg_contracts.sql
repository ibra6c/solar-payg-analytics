select
    contract_id,
    customer_id,
    product_id,
    agent_id,
    country_code,
    currency_code,
    started_on,
    cast(date_trunc('month', started_on) as date)                         as cohort_month,
    to_char(started_on, 'YYYY') || '-Q' || to_char(started_on, 'Q')       as cohort_quarter,
    deposit_local,
    daily_rate_local,
    term_days,
    deposit_local + daily_rate_local * term_days                          as total_price_local,
    started_on + term_days                                                as scheduled_end_on
from {{ source('raw', 'contracts') }}
