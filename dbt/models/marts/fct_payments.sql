-- One row per (deduplicated) payment, with BI-friendly attributes.

select
    p.payment_id,
    p.contract_id,
    p.paid_at,
    p.paid_on,
    p.paid_month,
    p.channel,
    d.country_name,
    d.currency_code,
    d.product_name,
    d.product_category,
    d.region,
    d.cohort_month,
    p.amount_local,
    p.amount_usd
from {{ ref('int_payments_usd') }} as p
inner join {{ ref('dim_contracts') }} as d
    on p.contract_id = d.contract_id
where p.paid_on <= {{ as_of_date() }}
