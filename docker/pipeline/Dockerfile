FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY generator/ generator/
COPY dbt/ dbt/
COPY docker/pipeline/run.sh docker/pipeline/run.sh

CMD ["bash", "docker/pipeline/run.sh"]
