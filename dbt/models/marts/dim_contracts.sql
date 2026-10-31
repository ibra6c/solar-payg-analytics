-- Contract dimension, denormalised for BI: product, customer, agent and country attributes.

select
    c.contract_id,
    c.customer_id,
    c.agent_id,
    c.product_id,
    p.product_name,
    p.product_category,
    c.country_code,
    co.country_name,
    c.currency_code,
    cu.region,
    cu.gender,
    cu.age_band,
    cu.occupation,
    a.agent_type,
    c.started_on,
    c.cohort_month,
    c.cohort_quarter,
    c.term_days,
    c.deposit_local,
    c.daily_rate_local,
    c.total_price_local,
    c.scheduled_end_on
from {{ ref('stg_contracts') }} as c
inner join {{ ref('stg_products') }}  as p  on c.product_id   = p.product_id
inner join {{ ref('stg_countries') }} as co on c.country_code = co.country_code
inner join {{ ref('stg_customers') }} as cu on c.customer_id  = cu.customer_id
inner join {{ ref('stg_agents') }}    as a  on c.agent_id     = a.agent_id
