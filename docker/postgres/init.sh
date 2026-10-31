#!/bin/bash
# Runs once, on the first start of the Postgres container (empty volume).
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<-EOSQL
    -- analytics warehouse, written by the pipeline (generator + dbt)
    CREATE DATABASE warehouse;

    -- Superset metadata (users, charts, dashboards)
    CREATE ROLE superset LOGIN PASSWORD '${SUPERSET_DB_PASSWORD}';
    CREATE DATABASE superset OWNER superset;

    -- read-only role Superset uses to query the marts (grants are managed by dbt)
    CREATE ROLE superset_reader LOGIN PASSWORD '${READER_PASSWORD}';
    GRANT CONNECT ON DATABASE warehouse TO superset_reader;
EOSQL
