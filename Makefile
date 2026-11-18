# Waffle Bros POS: everyday commands.  Run `make` (or `make help`) to list them.
#
#   make start      build everything and run the POS on http://localhost:4000
#   make dev        backend with auto-reload + screens with hot reload on http://localhost:5173
#   make up         run it in Docker instead (data kept in the pos-data volume)
#   make check      everything CI runs: lint, types, tests, OpenAPI drift, screens build

SHELL := /bin/bash
.DEFAULT_GOAL := help

PORT     ?= 4000
DATA_DIR ?= data
UV       ?= uv
NPM      ?= npm
FRONTEND := frontend
BACKUPS  ?= backups

export WB_PORT := $(PORT)

.PHONY: help install install-backend install-frontend start run dev backend frontend build \
        test lint format typecheck openapi check pre-commit demo run-demo \
        up down restart logs ps backup pin-reset update clean

help: ## List the commands
	@awk 'BEGIN {FS = ":.*##"; printf "\nWaffle Bros POS\n\n"} /^[a-zA-Z_-]+:.*##/ { printf "  \033[1mmake %-14s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)
	@echo

# ---------- Setup ----------
install: install-backend install-frontend ## Install Python (uv) and screen (npm) dependencies

install-backend:
	$(UV) sync

install-frontend:
	cd $(FRONTEND) && $(NPM) ci

# ---------- Run ----------
start: install build run ## Install, build the screens and run the POS (one command)

run: ## Run the POS on http://localhost:4000 (screens must be built)
	WB_DATA_DIR=$(DATA_DIR) $(UV) run waffle-pos

dev: ## Backend (auto-reload, :4000) + screens with hot reload (:5173) together; Ctrl+C stops both
	@trap 'kill 0' EXIT INT TERM; \
	  WB_DATA_DIR=$(DATA_DIR) $(UV) run uvicorn --factory waffle_pos.app:create_app --reload \
	    --reload-dir src --host 0.0.0.0 --port $(PORT) & \
	  (cd $(FRONTEND) && $(NPM) run dev) & \
	  wait

backend: ## Only the backend with auto-reload
	WB_DATA_DIR=$(DATA_DIR) $(UV) run uvicorn --factory waffle_pos.app:create_app --reload \
	  --reload-dir src --host 0.0.0.0 --port $(PORT)

frontend: ## Only the screens with hot reload on :5173 (API calls go to :4000)
	cd $(FRONTEND) && $(NPM) run dev

build: ## Build the screens into frontend/dist
	cd $(FRONTEND) && $(NPM) run build

demo: ## Create demo data in data-demo/ (never touches real data)
	$(UV) run python -m waffle_pos.demo

run-demo: demo ## Run the POS on the demo data
	WB_DATA_DIR=data-demo $(UV) run waffle-pos

# ---------- Quality ----------
lint: ## ruff lint + format check
	$(UV) run ruff check
	$(UV) run ruff format --check

format: ## Auto-fix lint issues and format the code
	$(UV) run ruff check --fix
	$(UV) run ruff format

typecheck: ## mypy --strict
	$(UV) run mypy

test: ## pytest with coverage
	$(UV) run pytest

openapi: ## Regenerate docs/openapi.json after API changes
	$(UV) run python -m waffle_pos.openapi

check: lint typecheck test build ## Everything CI runs (backend checks + screens build)
	$(UV) run python -m waffle_pos.openapi --check

pre-commit: ## Run the pre-commit hooks on every file
	$(UV) run pre-commit run --all-files

# ---------- Docker ----------
up: ## Build and start in Docker (http://localhost:4000)
	docker compose up -d --build

down: ## Stop the Docker container (data stays in the pos-data volume)
	docker compose down

restart: ## Restart the Docker container
	docker compose restart

logs: ## Follow the Docker logs
	docker compose logs -f --tail=100

ps: ## Show the container and its health
	docker compose ps

# ---------- Data ----------
backup: ## Copy the local database to backups/ (safe while the POS is running)
	@mkdir -p $(BACKUPS)
	@$(UV) run python -c "import sqlite3, sys; src = sqlite3.connect(sys.argv[1]); dst = sqlite3.connect(sys.argv[2]); src.backup(dst); dst.close(); src.close(); print('Saved', sys.argv[2])" \
	  "$(DATA_DIR)/waffle-bros.db" "$(BACKUPS)/waffle-bros-$$(date +%Y%m%d-%H%M%S).db"

pin-reset: ## Forget the admin PIN (it goes back to 1234); stop the POS first
	@$(UV) run python -c "import sqlite3, sys; c = sqlite3.connect(sys.argv[1]); n = c.execute(\"DELETE FROM settings WHERE key = 'module:admin'\").rowcount; c.commit(); print('PIN reset to 1234' if n else 'PIN was already the default')" \
	  "$(DATA_DIR)/waffle-bros.db"

update: ## Pull the latest code from GitHub and reinstall
	git pull --ff-only
	$(MAKE) install build

clean: ## Remove build output and caches (keeps your data)
	rm -rf $(FRONTEND)/dist .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	find . -name __pycache__ -type d -prune -not -path './.venv/*' -exec rm -rf {} +
