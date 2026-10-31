FROM apache/superset:6.0.0

# The official image no longer ships database drivers: add the Postgres one
# (used both for the metadata database and for the warehouse connection).
USER root
RUN . /app/.venv/bin/activate \
    && (uv pip install --no-cache psycopg2-binary || pip install --no-cache-dir psycopg2-binary)
USER superset
