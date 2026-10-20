.DEFAULT_GOAL := help
VENV ?= .venv
PY := $(VENV)/bin/python

.PHONY: help venv install test lint fmt typecheck build example clean

help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

venv: ## Create virtualenv
	test -d $(VENV) || python3 -m venv $(VENV)

install: venv ## Install package with dev + example extras
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -e ".[dev,examples]" python-multipart

test: ## Run tests
	$(PY) -m pytest

lint: ## Ruff + mypy
	$(VENV)/bin/ruff check src tests examples
	$(VENV)/bin/ruff format --check src tests examples
	$(VENV)/bin/mypy

fmt: ## Format and autofix
	$(VENV)/bin/ruff format src tests examples
	$(VENV)/bin/ruff check --fix src tests examples

typecheck: ## mypy --strict on the package
	$(VENV)/bin/mypy

build: ## Build sdist + wheel into dist/
	$(VENV)/bin/pip install build
	$(PY) -m build

example: ## Run the FastAPI checkout example on :8000 (needs BKASH_* env vars)
	$(VENV)/bin/uvicorn examples.fastapi_checkout.main:app --reload --port 8000

clean: ## Remove build artefacts and caches
	rm -rf dist build .pytest_cache .ruff_cache .mypy_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
