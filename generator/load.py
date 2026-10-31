"""
Load the generated CSV files into the `raw` schema of the warehouse (Postgres).

Tables are recreated on every run, so the load is idempotent.
Connection settings come from the same environment variables dbt uses.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import psycopg

DDL = {
    "countries": """
        country_code   text primary key,
        country_name   text not null,
        currency_code  text not null""",
    "fx_rates": """
        country_code   text not null,
        currency_code  text not null,
        rate_month     date not null,
        local_per_usd  numeric(14, 4) not null""",
    "products": """
        product_id     text primary key,
        product_name   text not null,
        category       text not null,
        deposit_usd    numeric(10, 2) not null,
        daily_rate_usd numeric(10, 2) not null,
        term_days      integer not null""",
    "agents": """
        agent_id       text primary key,
        country_code   text not null,
        region         text not null,
        agent_type     text not null,
        onboarded_on   date not null""",
    "customers": """
        customer_id    text primary key,
        country_code   text not null,
        region         text not null,
        gender         text,
        age_band       text,
        occupation     text,
        registered_at  timestamp not null""",
    "contracts": """
        contract_id      text primary key,
        customer_id      text not null,
        product_id       text not null,
        agent_id         text not null,
        country_code     text not null,
        currency_code    text not null,
        started_on       date not null,
        deposit_local    numeric(14, 2) not null,
        daily_rate_local numeric(14, 2) not null,
        term_days        integer not null""",
    # no primary key on purpose: the raw feed contains duplicated events
    "payments": """
        payment_id          text not null,
        provider_reference  text not null,
        contract_id         text not null,
        paid_at             timestamp not null,
        amount_local        numeric(14, 2) not null,
        currency_code       text not null,
        channel             text not null,
        ingested_at         timestamp not null""",
}


def conninfo() -> str:
    return (
        f"host={os.getenv('WAREHOUSE_HOST', 'localhost')} "
        f"port={os.getenv('WAREHOUSE_PORT', '5432')} "
        f"dbname={os.getenv('WAREHOUSE_DB', 'warehouse')} "
        f"user={os.getenv('WAREHOUSE_USER', 'postgres')} "
        f"password={os.getenv('WAREHOUSE_PASSWORD', 'postgres')}"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", type=Path, default=Path(__file__).resolve().parent.parent / "data" / "raw")
    ap.add_argument("--schema", default="raw")
    args = ap.parse_args()

    with psycopg.connect(conninfo(), autocommit=False) as conn, conn.cursor() as cur:
        cur.execute(f"create schema if not exists {args.schema}")
        for table, columns in DDL.items():
            path = args.src / f"{table}.csv"
            cur.execute(f"drop table if exists {args.schema}.{table} cascade")
            cur.execute(f"create table {args.schema}.{table} ({columns})")
            with open(path, encoding="utf-8") as f, cur.copy(
                f"copy {args.schema}.{table} from stdin with (format csv, header true)"
            ) as copy:
                while chunk := f.read(1 << 20):
                    copy.write(chunk)
            # fresh tables have no statistics: without this, the planner picks
            # nested loops on the downstream views and dbt runs become very slow
            cur.execute(f"analyze {args.schema}.{table}")
            cur.execute(f"select count(*) from {args.schema}.{table}")
            print(f"  {args.schema}.{table:<10} {cur.fetchone()[0]:>9,} rows")
        conn.commit()


if __name__ == "__main__":
    main()
