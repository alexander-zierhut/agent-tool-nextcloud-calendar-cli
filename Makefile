.PHONY: help install up down test test-unit test-integration lint docs clean
PY ?= python3
VENV ?= .venv

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Create a venv and install the CLI (editable, with test deps)
	$(PY) -m venv $(VENV)
	. $(VENV)/bin/activate && pip install -q -e '.[test]'

up: ## Boot the local test backend (Nextcloud 35 + Mailpit) and seed it
	docker compose up -d
	./scripts/seed.sh

down: ## Stop and remove the local test backend (data included)
	docker compose down -v

test-integration: ## Run only the tests against the local stack (make up first)
	. $(VENV)/bin/activate && NEXTCLOUDCALENDAR_REQUIRE_INTEGRATION=1 python -m pytest -m integration

test: ## Run the full suite (integration tests need `make up`; they skip without)
	. $(VENV)/bin/activate && python -m pytest

test-unit: ## Run the hermetic tests (no account, no backend, no token)
	# The MARKER is the source of truth, never a file list.
	. $(VENV)/bin/activate && python -m pytest -m "not integration"

lint: ## Lint with ruff (not a declared dep: pip install ruff, or use uvx/pipx)
	@command -v ruff >/dev/null 2>&1 || { echo "ruff not found. pip install ruff"; exit 1; }
	ruff check src tests scripts

docs: ## Regenerate docs/COMMANDS.md from the live command tree
	. $(VENV)/bin/activate && python scripts/gen_docs.py

clean: ## Remove build artifacts and caches
	rm -rf dist build *.egg-info src/*.egg-info .pytest_cache
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
