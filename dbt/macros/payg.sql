{#
    Business rules shared across models, kept in one place.
#}

{# Portfolio-at-risk bucket from a number of days in arrears #}
{% macro par_bucket(days_in_arrears) -%}
    case
        when {{ days_in_arrears }} <= 0  then '0. Current'
        when {{ days_in_arrears }} <= 30 then '1. 1-30 days'
        when {{ days_in_arrears }} <= 60 then '2. 31-60 days'
        when {{ days_in_arrears }} <= 90 then '3. 61-90 days'
        else '4. 90+ days'
    end
{%- endmacro %}

{# Expected cumulative amount after n days on book: deposit + daily rate, capped at the full price #}
{% macro expected_cumulative(deposit, daily_rate, term_days, days_on_book) -%}
    ({{ deposit }} + {{ daily_rate }} * least({{ term_days }}, greatest({{ days_on_book }}, 0)))
{%- endmacro %}

{% macro as_of_date() -%}
    cast('{{ var("as_of_date") }}' as date)
{%- endmacro %}
