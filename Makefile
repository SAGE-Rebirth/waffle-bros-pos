# Waffle Bros POS.  Run `make` to list the commands.
#
#   web  nginx serving the screens on http://localhost:4000, forwarding /api to ...
#   api  the FastAPI backend, with the SQLite database in the pos-data volume.

SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE     := docker compose
DEV_COMPOSE := docker compose -p waffle-bros-dev -f compose.yaml -f compose.dev.yaml
BACKUPS     ?= backups

# Run inside the api container: copy the live database safely and print it to stdout.
BACKUP_PY := import sqlite3, sys, tempfile; \
  t = tempfile.NamedTemporaryFile(suffix='.db'); \
  s = sqlite3.connect('/data/waffle-bros.db'); d = sqlite3.connect(t.name); \
  s.backup(d); d.close(); s.close(); \
  sys.stdout.buffer.write(open(t.name, 'rb').read())

PIN_RESET_PY := import sqlite3; c = sqlite3.connect('/data/waffle-bros.db'); \
  n = c.execute(\"DELETE FROM settings WHERE key = 'module:admin'\").rowcount; c.commit(); \
  print('PIN reset to 1234' if n else 'PIN was already the default')

.PHONY: help up down logs dev check backup pin-reset

help: ## List the commands
	@awk 'BEGIN {FS = ":.*##"; printf "\nWaffle Bros POS\n\n"} /^[a-z-]+:.*##/ { printf "  \033[1mmake %-10s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)
	@echo

up: ## Build and start the POS (web + api) on http://localhost:4000
	$(COMPOSE) up -d --build --wait
	@echo "POS is running on http://localhost:4000"

down: ## Stop the POS (your data stays in the pos-data volume)
	$(COMPOSE) down

logs: ## Follow the logs of both services
	$(COMPOSE) logs -f --tail=100

dev: ## Live-reload copy: screens :5173, API docs :8000/docs, own test data. Ctrl+C stops
	$(DEV_COMPOSE) up --build

check: ## What CI checks: lint, types, tests, OpenAPI drift, screens build (needs uv + npm)
	uv run ruff check
	uv run ruff format --check
	uv run mypy
	uv run pytest
	uv run python -m waffle_pos.openapi --check
	cd frontend && { [ -d node_modules ] || npm ci; } && npm run build

backup: ## Save a copy of the live database to backups/ (safe while the POS is running)
	@mkdir -p $(BACKUPS)
	@f="$(BACKUPS)/waffle-bros-$$(date +%Y%m%d-%H%M%S).db"; \
	  if $(COMPOSE) exec -T api python -c "$(BACKUP_PY)" > "$$f"; then echo "Saved $$f"; \
	  else rm -f -- "$$f"; echo "Backup failed. Is the POS running? (make up)"; exit 1; fi

pin-reset: ## Forget the admin PIN (it goes back to 1234). Restarts the api briefly
	$(COMPOSE) stop api
	@$(COMPOSE) run --rm --no-deps api python -c "$(PIN_RESET_PY)"
	$(COMPOSE) up -d --wait api
