#!/bin/bash
# generate synthetic data -> load into raw schema -> dbt build (models + tests)
set -euo pipefail
cd "$(dirname "$0")/../.."

RAW_DIR="${RAW_DIR:-/tmp/raw}"

echo "==> 1/3 Generating synthetic PAYG data"
python generator/generate.py --contracts "${N_CONTRACTS:-12000}" --out "$RAW_DIR"

echo "==> 2/3 Loading into the warehouse (schema raw)"
python generator/load.py --src "$RAW_DIR"

echo "==> 3/3 dbt build"
cd dbt
dbt build --profiles-dir .
