-- Payments converted to USD at the monthly rate of the payment month.

select
    p.payment_id,
    p.provider_reference,
    p.contract_id,
    c.country_code,
    p.paid_at,
    p.paid_on,
    p.paid_month,
    p.channel,
    p.currency_code,
    p.amount_local,
    round(p.amount_local * fx.usd_per_local, 4) as amount_usd
from {{ ref('stg_payments') }} as p
inner join {{ ref('stg_contracts') }} as c
    on p.contract_id = c.contract_id
inner join {{ ref('stg_fx_rates') }} as fx
    on  c.country_code = fx.country_code
    and p.paid_month   = fx.rate_month
