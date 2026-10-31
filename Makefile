.PHONY: up down reset logs pipeline provision lint

## Start the whole stack: Postgres, pipeline (data + dbt), Superset, dashboard provisioning
up:
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example")
	docker compose up -d --build
	@echo "Superset: http://localhost:$${SUPERSET_HOST_PORT:-8088}  (admin / admin)"

## Stop containers (data is kept)
down:
	docker compose down

## Stop and delete all data, then start from scratch
reset:
	docker compose down -v
	$(MAKE) up

logs:
	docker compose logs -f pipeline superset-provision

## Re-run the data pipeline only (new data + dbt build)
pipeline:
	docker compose run --rm pipeline

## Re-apply dashboards as code (idempotent)
provision:
	docker compose run --rm superset-provision

lint:
	ruff check generator superset
