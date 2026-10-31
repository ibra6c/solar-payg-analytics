select
    agent_id,
    country_code,
    region,
    agent_type,
    onboarded_on
from {{ source('raw', 'agents') }}
