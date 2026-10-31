-- Monthly collections vs. expected (billing), in the same long currency format
-- as rpt_cumulative_collections (see that model for the rationale).

with paid as (
    select
        paid_month          as month,
        country_name,
        currency_code,
        product_name,
        channel,
        count(*)            as n_payments,
        sum(amount_local)   as paid_local,
        sum(amount_usd)     as paid_usd
    from {{ ref('fct_payments') }}
    group by 1, 2, 3, 4, 5
),

expected as (
    select
        snapshot_month      as month,
        country_name,
        currency_code,
        product_name,
        sum(expected_local) as expected_local,
        sum(expected_usd)   as expected_usd
    from {{ ref('fct_contract_monthly') }}
    group by 1, 2, 3, 4
),

-- expected amounts are not split by channel: attach them to a dedicated row
unioned as (
    select month, country_name, currency_code, product_name, channel,
           n_payments, paid_local, paid_usd,
           0 as expected_local, 0 as expected_usd
    from paid
    union all
    select month, country_name, currency_code, product_name, '(billing)' as channel,
           0, 0, 0,
           expected_local, expected_usd
    from expected
)

select month, country_name, product_name, channel,
       'USD' as currency_view, 'USD' as currency_code,
       n_payments, paid_usd as paid, expected_usd as expected
from unioned
union all
select month, country_name, product_name, channel,
       'Local' as currency_view, currency_code,
       n_payments, paid_local as paid, expected_local as expected
from unioned
