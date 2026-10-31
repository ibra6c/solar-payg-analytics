-- Contract x month spine, from the contract's start month to the reporting month.
-- For each month we compute what was expected (schedule) and what was actually paid,
-- in local currency and in USD (each month's flows converted at that month's rate).

with contracts as (
    select * from {{ ref('stg_contracts') }}
    where started_on <= {{ as_of_date() }}
),

spine as (
    select
        c.contract_id,
        cast(m as date)                                                            as month_start,
        least(cast(m + interval '1 month - 1 day' as date), {{ as_of_date() }})    as month_end
    from contracts as c
    cross join lateral generate_series(
        c.cohort_month,
        date_trunc('month', {{ as_of_date() }}),
        interval '1 month'
    ) as m
),

monthly_payments as (
    select
        contract_id,
        paid_month,
        sum(amount_local) as paid_local,
        sum(amount_usd)   as paid_usd,
        count(*)          as n_payments
    from {{ ref('int_payments_usd') }}
    where paid_on <= {{ as_of_date() }}
    group by 1, 2
),

scheduled as (
    select
        s.contract_id,
        s.month_start,
        s.month_end,
        c.country_code,
        c.daily_rate_local,
        c.total_price_local,
        (s.month_end - c.started_on)                                        as days_on_book,
        (extract(year from age(s.month_start, c.cohort_month)) * 12
            + extract(month from age(s.month_start, c.cohort_month)))::int as months_on_book,
        {{ expected_cumulative('c.deposit_local', 'c.daily_rate_local', 'c.term_days',
                               '(s.month_end - c.started_on)') }}          as expected_cum_local,
        coalesce(mp.paid_local, 0)                                          as paid_local,
        coalesce(mp.paid_usd, 0)                                            as paid_usd,
        coalesce(mp.n_payments, 0)                                          as n_payments
    from spine as s
    inner join contracts as c using (contract_id)
    left join monthly_payments as mp
        on  s.contract_id = mp.contract_id
        and s.month_start = mp.paid_month
),

with_increments as (
    select
        *,
        expected_cum_local - coalesce(
            lag(expected_cum_local) over (partition by contract_id order by month_start), 0
        ) as expected_local
    from scheduled
)

select
    w.contract_id,
    w.month_start,
    w.month_end,
    w.months_on_book,
    w.days_on_book,
    w.daily_rate_local,
    w.total_price_local,
    fx.usd_per_local,

    -- flows of the month
    w.expected_local,
    w.expected_local * fx.usd_per_local                                                   as expected_usd,
    w.paid_local,
    w.paid_usd,
    w.n_payments,

    -- cumulative positions at month end
    w.expected_cum_local,
    sum(w.expected_local * fx.usd_per_local)
        over (partition by w.contract_id order by w.month_start)                          as expected_cum_usd,
    sum(w.paid_local) over (partition by w.contract_id order by w.month_start)           as paid_cum_local,
    sum(w.paid_usd)   over (partition by w.contract_id order by w.month_start)           as paid_cum_usd
from with_increments as w
inner join {{ ref('stg_fx_rates') }} as fx
    on  w.country_code = fx.country_code
    and w.month_start  = fx.rate_month
