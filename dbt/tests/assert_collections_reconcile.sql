-- Reconciliation: total paid in the monthly snapshot = total of deduplicated payments.
-- Catches fan-out joins and dropped rows between the payment and contract grains.
with snapshot as (
    select sum(paid_local) as total from {{ ref('fct_contract_monthly') }}
),
payments as (
    select sum(amount_local) as total from {{ ref('fct_payments') }}
)
select s.total as snapshot_total, p.total as payments_total
from snapshot as s cross join payments as p
where abs(s.total - p.total) > 0.01
