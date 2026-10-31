-- Cumulative collection curves by cohort and month on book.
--
-- "Long" currency format: every row exists twice, once with currency_view = 'USD'
-- and once with currency_view = 'Local'. A single-select native filter on
-- currency_view in Superset then acts as the currency toggle that a Power BI
-- field parameter / DAX switch would normally provide.

with base as (
    select
        cohort_month,
        cohort_quarter,
        months_on_book,
        country_name,
        currency_code,
        product_name,
        product_category,
        count(*)                as contracts,
        sum(expected_cum_local) as expected_cum_local,
        sum(paid_cum_local)     as paid_cum_local,
        sum(expected_cum_usd)   as expected_cum_usd,
        sum(paid_cum_usd)       as paid_cum_usd
    from {{ ref('fct_contract_monthly') }}
    group by 1, 2, 3, 4, 5, 6, 7
)

-- A cohort quarter is "complete" at a given month on book when even its last
-- sales month has reached that age: beyond that, the curve only reflects the
-- first weeks of the quarter and becomes noisy.
, flagged as (
    select
        *,
        (cast(date_trunc('quarter', cohort_month) as date) + interval '2 months'
            + months_on_book * interval '1 month')
            <= date_trunc('month', {{ as_of_date() }})          as is_complete_period
    from base
)

select
    cohort_month, cohort_quarter, months_on_book, is_complete_period,
    country_name, product_name, product_category,
    'USD'                as currency_view,
    'USD'                as currency_code,
    contracts,
    expected_cum_usd     as expected_cum,
    paid_cum_usd         as paid_cum
from flagged

union all

select
    cohort_month, cohort_quarter, months_on_book, is_complete_period,
    country_name, product_name, product_category,
    'Local'              as currency_view,
    currency_code,
    contracts,
    expected_cum_local   as expected_cum,
    paid_cum_local       as paid_cum
from flagged
