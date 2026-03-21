.PHONY: help setup dev-up dev-down dev-init \
       dev-func dev-web dev-start dev-all dev-logs dev-rebuild \
       test-upload test test-int lint fmt check clean _free-ports

SHELL  := /bin/bash
.DEFAULT_GOAL := help

# ───────────────────── Help ─────────────────────

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

# ───────────────────── Setup ─────────────────────

setup: ## Install Python deps + Azure Functions Core Tools
	uv sync --all-extras
	@echo ""
	@if command -v func &>/dev/null; then \
		echo "func tools: $$(func --version)"; \
	else \
		echo "Azure Functions Core Tools not found."; \
		echo "  Install with: bash scripts/setup_func_tools.sh"; \
	fi

# ───────────────────── Port cleanup ─────────────────────

DEV_PORTS := 7071 1111 10000 10001 10002

_free-ports: ## Kill local processes holding dev ports
	@for p in $(DEV_PORTS); do \
		pids=$$(fuser $$p/tcp 2>/dev/null); \
		if [ -n "$$pids" ]; then \
			echo "Killing pid(s) $$pids on port $$p"; \
			fuser -k $$p/tcp 2>/dev/null || true; \
		fi; \
	done
	@sleep 1

# ───────────────────── Azurite (Docker) ─────────────────────

dev-up: ## Start Azurite container
	docker compose up -d
	@echo "Azurite running on localhost:10000 (blob), :10001 (queue), :10002 (table)"

dev-down: _free-ports ## Stop containers and free ports
	docker compose down

dev-init: dev-up ## Start Azurite + create storage containers
	uv run python scripts/init_storage.py

# ───────────────────── Function Host ─────────────────────

dev-func: _free-ports ## Start Azure Functions host (port 7071)
	@command -v func >/dev/null 2>&1 || { echo "ERROR: func not found. Run: bash scripts/setup_func_tools.sh"; exit 1; }
	func start --python

# ───────────────────── Website ─────────────────────

dev-web: _free-ports ## Start website dev server with API proxy (port 1111)
	uv run python scripts/dev_server.py

# ───────────────────── Full Stack ─────────────────────

dev-start: dev-init ## Print instructions to start all services
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║  Azurite is running. Start these in          ║"
	@echo "║  separate terminals:                         ║"
	@echo "║                                              ║"
	@echo "║  Terminal 1:  make dev-func                  ║"
	@echo "║  Terminal 2:  make dev-web                   ║"
	@echo "║                                              ║"
	@echo "║  Then test:   make test-upload               ║"
	@echo "║  Website:     http://localhost:1111           ║"
	@echo "║  Functions:   http://localhost:7071/api/health║"
	@echo "╚══════════════════════════════════════════════╝"

dev-all: _free-ports ## Full stack via docker-compose (Azurite + func + web)
	docker compose down --remove-orphans 2>/dev/null || true
	docker compose up --build -d
	@echo ""
	@echo "╔══════════════════════════════════════════════════════╗"
	@echo "║  All services starting via docker-compose:           ║"
	@echo "║                                                      ║"
	@echo "║  Website:    http://localhost:1111                    ║"
	@echo "║  Functions:  http://localhost:7071/api/health         ║"
	@echo "║  Azurite:    localhost:10000 (blob)                   ║"
	@echo "║                                                      ║"
	@echo "║  Logs:       make dev-logs                            ║"
	@echo "║  Stop:       docker compose down                      ║"
	@echo "╚══════════════════════════════════════════════════════╝"

dev-logs: ## Tail logs from all docker-compose services
	docker compose logs -f --tail=50

dev-rebuild: _free-ports ## Rebuild and restart all services
	docker compose down --remove-orphans 2>/dev/null || true
	docker compose up --build -d --force-recreate

# ───────────────────── Testing ─────────────────────

test-upload: ## Upload sample KML and trigger pipeline
	uv run python scripts/simulate_upload.py

test: ## Run unit tests
	uv run pytest tests/ -v -m "not integration"

test-int: ## Run integration tests (requires Azurite)
	uv run pytest tests/test_integration.py -v

lint: ## Lint with ruff
	uv run ruff check .

fmt: ## Format with ruff
	uv run ruff format .

check: lint test ## Lint + test

# ───────────────────── Cleanup ─────────────────────

clean: dev-down ## Stop Azurite and remove data volume
	docker volume rm kml-satellites_azurite-data 2>/dev/null || true
	@echo "Cleaned up."
