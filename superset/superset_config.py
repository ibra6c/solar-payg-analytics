"""
Superset configuration for the local stack.
Mounted into the container and picked up through SUPERSET_CONFIG_PATH.
"""

import os

SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]

# Metadata database (users, charts, dashboards) — not the analytics warehouse
SQLALCHEMY_DATABASE_URI = os.getenv(
    "SUPERSET_METADATA_URI",
    "postgresql+psycopg2://superset:superset@postgres:5432/superset",
)

FEATURE_FLAGS = {
    # Jinja in SQL Lab / virtual datasets ({{ filter_values(...) }}, {{ from_dttm }}, ...)
    "ENABLE_TEMPLATE_PROCESSING": True,
    "DASHBOARD_CROSS_FILTERS": True,
}

# Simple in-process cache, enough for a single-node demo
CACHE_CONFIG = {"CACHE_TYPE": "SimpleCache", "CACHE_DEFAULT_TIMEOUT": 300}
DATA_CACHE_CONFIG = CACHE_CONFIG

# Local demo: no HTTPS, so disable the strict security headers
TALISMAN_ENABLED = False
WTF_CSRF_ENABLED = True

# Nicer defaults for this project
BABEL_DEFAULT_LOCALE = os.getenv("SUPERSET_LOCALE", "en")
LANGUAGES = {"en": {"flag": "us", "name": "English"}, "fr": {"flag": "fr", "name": "French"}}
ROW_LIMIT = 50_000
