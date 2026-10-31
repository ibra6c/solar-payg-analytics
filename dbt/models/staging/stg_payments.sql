-- One row per real mobile-money transaction.
-- The raw feed is at-least-once, so duplicates are removed on provider_reference
-- (first ingested event wins).

with source as (
    select * from {{ source('raw', 'payments') }}
),

deduplicated as (
    select
        *,
        row_number() over (
            partition by provider_reference
            order by ingested_at, payment_id
        ) as event_rank
    from source
)

select
    payment_id,
    provider_reference,
    contract_id,
    paid_at,
    cast(paid_at as date)                          as paid_on,
    cast(date_trunc('month', paid_at) as date)     as paid_month,
    amount_local,
    currency_code,
    channel
from deduplicated
where event_rank = 1
