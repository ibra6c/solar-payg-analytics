-- Cumulative paid amount can only go up from one month to the next.
with ordered as (
    select
        contract_id,
        snapshot_month,
        paid_cum_local,
        lag(paid_cum_local) over (partition by contract_id order by snapshot_month) as previous
    from {{ ref('fct_contract_monthly') }}
)
select * from ordered
where paid_cum_local < previous
