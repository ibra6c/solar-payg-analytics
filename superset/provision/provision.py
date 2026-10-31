"""
Dashboards as code: provisions the "PAYG Portfolio Performance" dashboard in Superset
through its REST API.

What it does (idempotent — safe to re-run, objects are matched by name and updated):
  1. connects the analytics warehouse as a Superset database (read-only role)
  2. registers the dbt marts as datasets and attaches business metrics to them
  3. creates the charts
  4. creates the dashboard: layout, native filters (incl. a USD / Local currency toggle)
  5. optionally (--verify) runs every chart query through the chart-data API

Usage:
    python provision.py --url http://localhost:8088 --verify
Environment:
    SUPERSET_ADMIN_USER / SUPERSET_ADMIN_PASSWORD
    WAREHOUSE_SQLALCHEMY_URI   e.g. postgresql+psycopg2://superset_reader:***@postgres:5432/warehouse
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid

import requests

DATABASE_NAME = "PAYG Warehouse"
SCHEMA = "marts"
DASHBOARD_TITLE = "PAYG Portfolio Performance"
DASHBOARD_SLUG = "payg-portfolio"

# --------------------------------------------------------------------------- #
# Semantic layer: datasets and their metrics
# --------------------------------------------------------------------------- #

RATE = ".1%"
MONEY = ",.0f"

DATASETS = {
    "rpt_cumulative_collections": {
        "description": "Cumulative collection curves by cohort and months on book (dbt: rpt_cumulative_collections).",
        "metrics": [
            ("collection_rate", "Cumulative collection rate",
             "SUM(paid_cum) / NULLIF(SUM(expected_cum), 0)", RATE),
            ("paid_cum", "Paid (cumulative)", "SUM(paid_cum)", MONEY),
            ("expected_cum", "Expected (cumulative)", "SUM(expected_cum)", MONEY),
        ],
    },
    "rpt_collections_monthly": {
        "description": "Monthly collections vs. expected billing (dbt: rpt_collections_monthly).",
        "metrics": [
            ("collections", "Collections", "SUM(paid)", MONEY),
            ("expected", "Expected billing", "SUM(expected)", MONEY),
            ("monthly_collection_rate", "Monthly collection rate",
             "SUM(paid) / NULLIF(SUM(expected), 0)", RATE),
            ("payments", "Number of payments", "SUM(n_payments)", ",d"),
        ],
    },
    "fct_contract_monthly": {
        "description": "Month-end contract snapshot: arrears, PAR, status (dbt: fct_contract_monthly).",
        "metrics": [
            ("active_contracts", "Active contracts",
             "COUNT(*) FILTER (WHERE contract_status = 'Active')", ",d"),
            ("contracts", "Contracts", "COUNT(DISTINCT contract_id)", ",d"),
            ("par30", "PAR30 (balance)",
             "SUM(outstanding_usd) FILTER (WHERE contract_status = 'Active' AND days_in_arrears > 30)"
             " / NULLIF(SUM(outstanding_usd) FILTER (WHERE contract_status = 'Active'), 0)", RATE),
            ("repayment_rate", "Repayment rate (to date)",
             "SUM(paid_cum_usd) / NULLIF(SUM(expected_cum_usd), 0)", RATE),
            ("outstanding_usd", "Outstanding balance (USD)",
             "SUM(outstanding_usd) FILTER (WHERE contract_status = 'Active')", "$,.0f"),
            ("outstanding_by_bucket", "Outstanding balance (USD)", "SUM(outstanding_usd)", "$,.0f"),
        ],
    },
}

# Human-readable column names, applied to every dataset that has the column
COLUMN_LABELS = {
    "country_name": "Country", "product_name": "Product", "product_category": "Product category",
    "cohort_month": "Cohort month", "cohort_quarter": "Cohort quarter", "months_on_book": "Months on book",
    "currency_view": "Currency", "currency_code": "Currency code", "channel": "Payment channel",
    "par_bucket": "PAR bucket", "contract_status": "Contract status", "snapshot_month": "Month",
    "month": "Month", "region": "Region", "agent_type": "Agent type", "days_in_arrears": "Days in arrears",
}

# Fixed colours so PAR buckets read like a traffic light on every chart
LABEL_COLORS = {
    "0. Current": "#2E7D5B", "1. 1-30 days": "#E9B949", "2. 31-60 days": "#E8833A",
    "3. 61-90 days": "#D1495B", "4. 90+ days": "#7A1F2B",
}

LATEST = [{"expressionType": "SQL", "clause": "WHERE", "sqlExpression": "is_latest_snapshot"}]
PAYMENTS_ONLY = [{"expressionType": "SQL", "clause": "WHERE", "sqlExpression": "channel <> '(billing)'"}]
COMPLETE_COHORTS = [{"expressionType": "SQL", "clause": "WHERE", "sqlExpression": "is_complete_period"}]
ACTIVE_ONLY = [{"expressionType": "SQL", "clause": "WHERE", "sqlExpression": "contract_status = 'Active'"}]

# --------------------------------------------------------------------------- #
# Charts. `key` is a stable identifier used in the layout below.
# --------------------------------------------------------------------------- #

CHARTS = [
    dict(key="kpi_active", name="Active contracts", dataset="fct_contract_monthly",
         params=dict(viz_type="big_number", x_axis="snapshot_month", time_grain_sqla="P1M",
                     metric="active_contracts", y_axis_format=",d", show_trend_line=True,
                     start_y_axis_at_zero=False, compare_lag=1, compare_suffix="vs last month")),
    dict(key="kpi_rr", name="Repayment rate", dataset="fct_contract_monthly",
         params=dict(viz_type="big_number", x_axis="snapshot_month", time_grain_sqla="P1M",
                     metric="repayment_rate", y_axis_format=RATE, show_trend_line=True,
                     start_y_axis_at_zero=False, compare_lag=1, compare_suffix="vs last month",
                     subheader="Paid / expected since contract start")),
    dict(key="kpi_par30", name="PAR30", dataset="fct_contract_monthly",
         params=dict(viz_type="big_number", x_axis="snapshot_month", time_grain_sqla="P1M",
                     metric="par30", y_axis_format=RATE, show_trend_line=True,
                     start_y_axis_at_zero=False, compare_lag=1, compare_suffix="vs last month")),
    dict(key="kpi_outstanding", name="Outstanding balance (USD)", dataset="fct_contract_monthly",
         params=dict(viz_type="big_number", x_axis="snapshot_month", time_grain_sqla="P1M",
                     metric="outstanding_usd", y_axis_format="$,.3s", show_trend_line=True,
                     start_y_axis_at_zero=False, compare_lag=1, compare_suffix="vs last month")),
    dict(key="cohort_curves", name="Cumulative collection rate by cohort", dataset="rpt_cumulative_collections",
         description="Paid / expected since contract start, by months on book. One line per sales quarter.",
         params=dict(viz_type="echarts_timeseries_line", x_axis="months_on_book",
                     metrics=["collection_rate"], groupby=["cohort_quarter"],
                     adhoc_filters=COMPLETE_COHORTS,
                     y_axis_format=RATE, x_axis_title="Months on book", x_axis_title_margin=30,
                     show_legend=True, legendType="scroll", legendOrientation="top",
                     rich_tooltip=True, tooltipSortByMetric=True, markerEnabled=False,
                     truncateYAxis=True, y_axis_bounds=[0.5, 1], row_limit=10000)),
    dict(key="collections_by_country", name="Monthly collections by country", dataset="rpt_collections_monthly",
         description="Amounts follow the Currency filter. In 'Local', compare one country at a time.",
         params=dict(viz_type="echarts_timeseries_bar", x_axis="month", time_grain_sqla="P1M",
                     metrics=["collections"], groupby=["country_name"], stack="Stack",
                     adhoc_filters=PAYMENTS_ONLY, y_axis_format="~s", show_legend=True,
                     legendOrientation="top", rich_tooltip=True, row_limit=10000)),
    dict(key="monthly_rate", name="Monthly collection rate", dataset="rpt_collections_monthly",
         params=dict(viz_type="echarts_timeseries_line", x_axis="month", time_grain_sqla="P1M",
                     metrics=["monthly_collection_rate"], groupby=["country_name"],
                     y_axis_format=RATE, show_legend=True, legendOrientation="top",
                     rich_tooltip=True, truncateYAxis=True, y_axis_bounds=[0.4, 1.1], row_limit=10000)),
    dict(key="par_buckets", name="Portfolio at risk by bucket", dataset="fct_contract_monthly",
         description="Share of the active outstanding balance by days in arrears.",
         params=dict(viz_type="echarts_timeseries_bar", x_axis="snapshot_month", time_grain_sqla="P1M",
                     metrics=["outstanding_by_bucket"], groupby=["par_bucket"], stack="Stack",
                     contributionMode="row", adhoc_filters=ACTIVE_ONLY, y_axis_format=".0%",
                     sort_series_type="name", sort_series_ascending=True,
                     show_legend=True, legendOrientation="top", rich_tooltip=True, row_limit=10000)),
    dict(key="channels", name="Collections by payment channel", dataset="rpt_collections_monthly",
         params=dict(viz_type="pie", groupby=["channel"], metric="collections", adhoc_filters=PAYMENTS_ONLY,
                     show_labels=True, label_type="percent", labels_outside=False, donut=True,
                     innerRadius=40, outerRadius=80, show_legend=True, legendOrientation="right",
                     legendType="scroll", row_limit=15,
                     number_format="SMART_NUMBER", sort_by_metric=True)),
    dict(key="country_table", name="Portfolio by country and product", dataset="fct_contract_monthly",
         description="Latest month-end snapshot.",
         params=dict(viz_type="table", query_mode="aggregate", groupby=["country_name", "product_name"],
                     metrics=["contracts", "active_contracts", "repayment_rate", "par30", "outstanding_usd"],
                     adhoc_filters=LATEST, order_desc=True, row_limit=100, show_cell_bars=True,
                     table_timestamp_format="smart_date", include_search=False, allow_rearrange_columns=True,
                     column_config={
                         "repayment_rate": {"d3NumberFormat": RATE},
                         "par30": {"d3NumberFormat": RATE},
                         "outstanding_usd": {"d3NumberFormat": "$,.0f"},
                     })),
]

INTRO = """### Off-grid solar PAYG portfolio
Synthetic portfolio of **solar home systems and appliances sold on credit** in five
countries, repaid daily by mobile money.

* **Repayment rate** = paid / expected since contract start
* **PAR30** = share of the active outstanding balance more than 30 days in arrears
* **Currency** filter: switch amounts between USD and local currency

Data: `dbt` marts built on Postgres — see the GitHub repo for the models."""

# rows of the dashboard grid: (chart key | "markdown", width out of 12, height)
LAYOUT = [
    [("kpi_active", 3, 40), ("kpi_rr", 3, 40), ("kpi_par30", 3, 40), ("kpi_outstanding", 3, 40)],
    [("cohort_curves", 8, 60), ("markdown", 4, 60)],
    [("collections_by_country", 6, 55), ("monthly_rate", 6, 55)],
    [("par_buckets", 7, 55), ("channels", 5, 55)],
    [("country_table", 12, 60)],
]


# --------------------------------------------------------------------------- #
# Minimal API client
# --------------------------------------------------------------------------- #

def rison(value) -> str:
    """Tiny Rison encoder (enough for Superset list filters)."""
    if isinstance(value, dict):
        return "(" + ",".join(f"{k}:{rison(v)}" for k, v in value.items()) + ")"
    if isinstance(value, (list, tuple)):
        return "!(" + ",".join(rison(v) for v in value) + ")"
    if isinstance(value, bool):
        return "!t" if value else "!f"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("!", "!!").replace("'", "!'") + "'"


class Superset:
    def __init__(self, url: str, user: str, password: str):
        self.url = url.rstrip("/")
        self.s = requests.Session()
        r = self.s.post(f"{self.url}/api/v1/security/login",
                        json={"username": user, "password": password, "provider": "db", "refresh": True})
        r.raise_for_status()
        self.s.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        csrf = self.s.get(f"{self.url}/api/v1/security/csrf_token/")
        csrf.raise_for_status()
        self.s.headers.update({"X-CSRFToken": csrf.json()["result"], "Referer": self.url})

    def call(self, method: str, path: str, **kw) -> dict:
        r = self.s.request(method, f"{self.url}/api/v1/{path}", **kw)
        if not r.ok:
            raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:800]}")
        return r.json() if r.content else {}

    def find(self, resource: str, **equals) -> dict | None:
        filters = [{"col": k, "opr": "eq", "value": v} for k, v in equals.items()]
        q = rison({"filters": filters, "page_size": 100})
        result = self.call("GET", f"{resource}/?q={q}")["result"]
        return result[0] if result else None

    def upsert(self, resource: str, match: dict, payload: dict) -> int:
        existing = self.find(resource, **match)
        if existing:
            self.call("PUT", f"{resource}/{existing['id']}", json=payload)
            return existing["id"]
        return self.call("POST", f"{resource}/", json=payload)["id"]


def wait_until_healthy(url: str, timeout: int = 300) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if requests.get(f"{url}/health", timeout=5).ok:
                return
        except requests.RequestException:
            pass
        print("  waiting for Superset ...")
        time.sleep(5)
    sys.exit(f"Superset not reachable at {url}")


# --------------------------------------------------------------------------- #
# Provisioning steps
# --------------------------------------------------------------------------- #

def ensure_database(api: Superset, uri: str) -> int:
    payload = {
        "database_name": DATABASE_NAME,
        "sqlalchemy_uri": uri,
        "expose_in_sqllab": True,
        "allow_ctas": False,
        "allow_dml": False,
        "extra": json.dumps({"schemas_allowed_for_file_upload": [], "allows_virtual_table_explore": True}),
    }
    db_id = api.upsert("database", {"database_name": DATABASE_NAME}, payload)
    print(f"  database '{DATABASE_NAME}' -> id {db_id}")
    return db_id


def ensure_dataset(api: Superset, db_id: int, table: str, spec: dict) -> int:
    existing = api.find("dataset", table_name=table)
    if existing:
        ds_id = existing["id"]
        api.call("PUT", f"dataset/{ds_id}/refresh")  # pick up new dbt columns
    else:
        ds_id = api.call("POST", "dataset/", json={"database": db_id, "schema": SCHEMA, "table_name": table})["id"]

    current = api.call("GET", f"dataset/{ds_id}")["result"]
    by_name = {m["metric_name"]: m["id"] for m in current["metrics"]}
    metrics = [
        {**({"id": by_name[name]} if name in by_name else {}),
         "metric_name": name, "verbose_name": label, "expression": expr, "d3format": fmt}
        for name, label, expr, fmt in spec["metrics"]
    ]
    columns = [
        {"id": c["id"], "column_name": c["column_name"], "verbose_name": COLUMN_LABELS.get(c["column_name"])}
        for c in current["columns"]
    ]
    api.call("PUT", f"dataset/{ds_id}",
             json={"description": spec["description"], "metrics": metrics, "columns": columns})
    print(f"  dataset {SCHEMA}.{table} -> id {ds_id} ({len(metrics)} metrics)")
    return ds_id


def ensure_chart(api: Superset, chart: dict, ds_id: int, dashboard_id: int) -> int:
    params = {"datasource": f"{ds_id}__table", "adhoc_filters": [], **chart["params"]}
    payload = {
        "slice_name": chart["name"],
        "viz_type": params["viz_type"],
        "datasource_id": ds_id,
        "datasource_type": "table",
        "params": json.dumps(params),
        "description": chart.get("description"),
        "dashboards": [dashboard_id],
    }
    chart_id = api.upsert("chart", {"slice_name": chart["name"]}, payload)
    print(f"  chart '{chart['name']}' -> id {chart_id}")
    return chart_id


def build_position(chart_ids: dict[str, int], names: dict[str, str]) -> dict:
    pos: dict = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": [], "parents": ["ROOT_ID"]},
        "HEADER_ID": {"type": "HEADER", "id": "HEADER_ID", "meta": {"text": DASHBOARD_TITLE}},
    }
    for r, row in enumerate(LAYOUT, start=1):
        row_id = f"ROW-{r}"
        pos["GRID_ID"]["children"].append(row_id)
        pos[row_id] = {"type": "ROW", "id": row_id, "children": [],
                       "parents": ["ROOT_ID", "GRID_ID"], "meta": {"background": "BACKGROUND_TRANSPARENT"}}
        for key, width, height in row:
            parents = ["ROOT_ID", "GRID_ID", row_id]
            if key == "markdown":
                node_id = f"MARKDOWN-{r}"
                pos[node_id] = {"type": "MARKDOWN", "id": node_id, "children": [], "parents": parents,
                                "meta": {"width": width, "height": height, "code": INTRO}}
            else:
                node_id = f"CHART-{key}"
                pos[node_id] = {"type": "CHART", "id": node_id, "children": [], "parents": parents,
                                "meta": {"width": width, "height": height,
                                         "chartId": chart_ids[key], "sliceName": names[key]}}
            pos[row_id]["children"].append(node_id)
    return pos


def native_filter(name: str, ds_id: int, column: str, *, excluded: list[int], default=None,
                  multi: bool = True, required: bool = False) -> dict:
    default_mask = {"extraFormData": {}, "filterState": {}, "ownState": {}}
    if default is not None:
        default_mask = {
            "extraFormData": {"filters": [{"col": column, "op": "IN", "val": default}]},
            "filterState": {"value": default},
            "ownState": {},
        }
    return {
        "id": f"NATIVE_FILTER-{uuid.uuid5(uuid.NAMESPACE_URL, DASHBOARD_SLUG + column).hex[:10]}",
        "name": name,
        "filterType": "filter_select",
        "type": "NATIVE_FILTER",
        "targets": [{"datasetId": ds_id, "column": {"name": column}}],
        "controlValues": {
            "enableEmptyFilter": required,
            "defaultToFirstItem": False,
            "multiSelect": multi,
            "searchAllOptions": False,
            "inverseSelection": False,
        },
        "defaultDataMask": default_mask,
        "cascadeParentIds": [],
        "scope": {"rootPath": ["ROOT_ID"], "excluded": excluded},
        "description": "",
    }


def ensure_dashboard(api: Superset) -> int:
    return api.upsert("dashboard", {"slug": DASHBOARD_SLUG},
                      {"dashboard_title": DASHBOARD_TITLE, "slug": DASHBOARD_SLUG, "published": True})


def finalize_dashboard(api: Superset, dash_id: int, chart_ids: dict[str, int], ds_ids: dict[str, int]) -> None:
    names = {c["key"]: c["name"] for c in CHARTS}
    on_snapshot = [chart_ids[c["key"]] for c in CHARTS if c["dataset"] == "fct_contract_monthly"]
    filters = [
        # Currency toggle: only the report datasets carry currency_view
        native_filter("Currency", ds_ids["rpt_collections_monthly"], "currency_view",
                      excluded=on_snapshot, default=["USD"], multi=False, required=True),
        native_filter("Country", ds_ids["fct_contract_monthly"], "country_name", excluded=[]),
        native_filter("Product", ds_ids["fct_contract_monthly"], "product_name", excluded=[]),
    ]
    metadata = {
        "native_filter_configuration": filters,
        "color_scheme": "supersetColors",
        "cross_filters_enabled": True,
        "refresh_frequency": 0,
        "timed_refresh_immune_slices": [],
        "expanded_slices": {},
        "default_filters": "{}",
        "shared_label_colors": [],
        "label_colors": LABEL_COLORS,
    }
    api.call("PUT", f"dashboard/{dash_id}", json={
        "dashboard_title": DASHBOARD_TITLE,
        "slug": DASHBOARD_SLUG,
        "published": True,
        "position_json": json.dumps(build_position(chart_ids, names)),
        "json_metadata": json.dumps(metadata),
    })
    print(f"  dashboard '{DASHBOARD_TITLE}' -> /superset/dashboard/{DASHBOARD_SLUG}/")


# --------------------------------------------------------------------------- #
# Verification: run each chart's query through the chart-data API
# --------------------------------------------------------------------------- #

def chart_query(chart: dict, ds_id: int) -> dict:
    p = chart["params"]
    metrics = p.get("metrics") or [p["metric"]]
    columns: list = []
    if "x_axis" in p:
        axis = p["x_axis"]
        if p.get("time_grain_sqla"):
            axis = {"label": axis, "sqlExpression": axis, "expressionType": "SQL",
                    "columnType": "BASE_AXIS", "timeGrain": p["time_grain_sqla"]}
        columns.append(axis)
    columns += p.get("groupby", [])
    filters = p.get("adhoc_filters", [])
    where = " AND ".join(f"({f['sqlExpression']})" for f in filters)
    return {
        "datasource": {"id": ds_id, "type": "table"},
        "force": True,
        "queries": [{
            "columns": columns,
            "metrics": metrics,
            "filters": [{"col": "currency_view", "op": "IN", "val": ["USD"]}]
            if chart["dataset"].startswith("rpt_") else [],
            "extras": {"where": where, "having": ""},
            "row_limit": 10000,
            "orderby": [],
        }],
        "result_format": "json",
        "result_type": "full",
    }


def verify(api: Superset, ds_ids: dict[str, int]) -> bool:
    ok = True
    for chart in CHARTS:
        try:
            res = api.call("POST", "chart/data", json=chart_query(chart, ds_ids[chart["dataset"]]))["result"][0]
            rows = res.get("rowcount", 0)
            status = "OK " if rows else "EMPTY"
            ok &= rows > 0
            print(f"  [{status}] {chart['name']:<40} {rows:>6} rows")
        except RuntimeError as e:
            ok = False
            print(f"  [FAIL] {chart['name']}: {e}")
    return ok


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.getenv("SUPERSET_URL", "http://localhost:8088"))
    ap.add_argument("--user", default=os.getenv("SUPERSET_ADMIN_USER", "admin"))
    ap.add_argument("--password", default=os.getenv("SUPERSET_ADMIN_PASSWORD", "admin"))
    ap.add_argument("--warehouse-uri", default=os.getenv(
        "WAREHOUSE_SQLALCHEMY_URI",
        "postgresql+psycopg2://superset_reader:reader@postgres:5432/warehouse"))
    ap.add_argument("--verify", action="store_true", help="run every chart query after provisioning")
    args = ap.parse_args()

    print(f"Provisioning {args.url}")
    wait_until_healthy(args.url)
    api = Superset(args.url, args.user, args.password)

    db_id = ensure_database(api, args.warehouse_uri)
    ds_ids = {table: ensure_dataset(api, db_id, table, spec) for table, spec in DATASETS.items()}
    dash_id = ensure_dashboard(api)
    chart_ids = {c["key"]: ensure_chart(api, c, ds_ids[c["dataset"]], dash_id) for c in CHARTS}
    finalize_dashboard(api, dash_id, chart_ids, ds_ids)

    if args.verify:
        print("Verifying chart queries")
        if not verify(api, ds_ids):
            sys.exit(1)
    print("Done.")


if __name__ == "__main__":
    main()
