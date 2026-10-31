-- A customer can never pay more than the full price of the contract
-- (the platform stops accepting payments once the device is paid off).
select contract_id, snapshot_month, paid_cum_local, d.total_price_local
from {{ ref('fct_contract_monthly') }} as f
inner join {{ ref('dim_contracts') }} as d using (contract_id)
where f.paid_cum_local > d.total_price_local + 0.01
