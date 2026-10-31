-- Month-end snapshot of every contract: arrears, PAR bucket, status, outstanding balance.
-- Grain: one row per contract and month.

with months as (
    select * from {{ ref('int_contract_months') }}
),

positions as (
    select
        *,
        greatest(expected_cum_local - paid_cum_local, 0)                    as arrears_local,
        greatest(total_price_local - paid_cum_local, 0)                     as outstanding_local,
        ceil(greatest(expected_cum_local - paid_cum_local, 0)
             / nullif(daily_rate_local, 0))::int                             as days_in_arrears
    from months
)

select
    p.contract_id,
    p.month_start                                            as snapshot_month,
    p.month_end                                              as snapshot_date,
    p.months_on_book,
    p.days_on_book,
    p.month_start = cast(date_trunc('month', {{ as_of_date() }}) as date)   as is_latest_snapshot,

    d.country_name,
    d.currency_code,
    d.product_name,
    d.product_category,
    d.region,
    d.agent_type,
    d.cohort_month,
    d.cohort_quarter,

    -- position
    p.days_in_arrears,
    {{ par_bucket('p.days_in_arrears') }}                    as par_bucket,
    case
        when p.paid_cum_local >= p.total_price_local          then 'Paid off'
        when p.days_in_arrears > {{ var('write_off_days') }}  then 'Written off'
        else 'Active'
    end                                                      as contract_status,

    -- amounts, local currency
    p.expected_local,
    p.paid_local,
    p.expected_cum_local,
    p.paid_cum_local,
    p.arrears_local,
    p.outstanding_local,

    -- amounts, USD
    p.expected_usd,
    p.paid_usd,
    p.expected_cum_usd,
    p.paid_cum_usd,
    p.arrears_local     * p.usd_per_local                    as arrears_usd,
    p.outstanding_local * p.usd_per_local                    as outstanding_usd,

    p.n_payments
from positions as p
inner join {{ ref('dim_contracts') }} as d
    on p.contract_id = d.contract_id
