.DEFAULT_GOAL := help
.PHONY: help install lint fmt type test test-int cov check run worker up down logs clean

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## Create the venv and install everything
	uv sync --locked
	uv run pre-commit install

lint:  ## Ruff check
	uv run ruff check src tests

fmt:  ## Ruff format + autofix
	uv run ruff check --fix src tests
	uv run ruff format src tests

type:  ## mypy (strict)
	uv run mypy

test:  ## Unit tests
	uv run pytest -m "not integration"

test-int:  ## Integration tests (needs Docker)
	uv run pytest -m integration

cov:  ## Unit tests with coverage
	uv run pytest -m "not integration" --cov --cov-report=term-missing

check: lint type test  ## Everything CI runs on a PR

run:  ## Run the bot locally (needs Redis + RabbitMQ)
	uv run python -m pdfbot

worker:  ## Run a Celery worker locally
	uv run celery --app=pdfbot.worker.celery_app worker --loglevel=info

up:  ## Bring up the whole stack
	docker compose up --build -d

down:  ## Tear it down (volumes survive)
	docker compose down

logs:  ## Follow bot and worker logs
	docker compose logs -f bot worker

clean:  ## Remove caches and build artefacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage dist build
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
