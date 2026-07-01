.PHONY: help setup dev-up dev-down dev-init \
       dev-func dev-web dev-start dev-all dev-logs dev-rebuild \
	test-upload test test-int lint fmt check smoke clean \
	_free-ports _free-func-port _free-web-ports \
	sast scan scan-iac scan-fs scan-image

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

DEV_FUNC_PORT := 7071
DEV_WEB_PORT := 4280
DEV_WEB_LEGACY_PORT := 1111
DEV_STORAGE_PORTS := 10000 10001 10002
DEV_WEB_PORTS := $(DEV_WEB_PORT) $(DEV_WEB_LEGACY_PORT)
DEV_PORTS := $(DEV_FUNC_PORT) $(DEV_WEB_PORTS) $(DEV_STORAGE_PORTS)

_free-func-port: ## Kill local processes holding the Functions port
	@for p in $(DEV_FUNC_PORT); do \
		pids=$$(fuser $$p/tcp 2>/dev/null); \
		if [ -n "$$pids" ]; then \
			echo "Killing pid(s) $$pids on port $$p"; \
			fuser -k $$p/tcp 2>/dev/null || true; \
		fi; \
	done
	@sleep 1

_free-web-ports: ## Kill local processes holding the website dev ports
	@for p in $(DEV_WEB_PORTS); do \
		pids=$$(fuser $$p/tcp 2>/dev/null); \
		if [ -n "$$pids" ]; then \
			echo "Killing pid(s) $$pids on port $$p"; \
			fuser -k $$p/tcp 2>/dev/null || true; \
		fi; \
	done
	@sleep 1

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

dev-func: _free-func-port ## Start Azure Functions host (port 7071)
	@command -v func >/dev/null 2>&1 || { echo "ERROR: func not found. Run: bash scripts/setup_func_tools.sh"; exit 1; }
	func start --python

# ───────────────────── Website ─────────────────────

dev-web: _free-web-ports ## Start website dev server with API proxy (port 4280)
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
	@echo "║  Website:     http://localhost:4280           ║"
	@echo "║  Functions:   http://localhost:7071/api/health║"
	@echo "╚══════════════════════════════════════════════╝"

dev-all: _free-ports ## Full stack via docker-compose (Azurite + func + web)
	docker compose down --remove-orphans 2>/dev/null || true
	docker compose up --build -d
	@echo ""
	@echo "╔══════════════════════════════════════════════════════╗"
	@echo "║  All services starting via docker-compose:           ║"
	@echo "║                                                      ║"
	@echo "║  Website:    http://localhost:4280                    ║"
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

test: ## Run unit tests (canonical — CI runs this exact command)
	uv run pytest tests/ -v -m "not integration" --tb=short --cov=treesight --cov-report=xml

test-int: ## Run integration tests (requires Azurite)
	uv run pytest tests/test_integration.py -v

lint: ## Static checks: ruff lint + format check + pyright (canonical — CI runs this)
	uv run ruff check .
	uv run ruff format --check .
	uv run pyright

fmt: ## Auto-format and autofix with ruff
	uv run ruff format .
	uv run ruff check --fix .

check: lint test ## Full local gate (lint + test) — identical to CI

# ───────────────────── Static analysis (Semgrep) ─────────────────────
# Single source of truth for Semgrep — local and CI run this exact command.
# Pinned version (via uvx) + pinned rule packs (no server-side auto rule
# selection) so results are reproducible and don't drift as the registry
# publishes new rules.
# CI sets SEMGREP_FORMAT=sarif + SEMGREP_OUTPUT=<file> to emit SARIF.
SEMGREP_VERSION ?= 1.163.0
SEMGREP ?= uvx --quiet semgrep@$(SEMGREP_VERSION)
SEMGREP_FORMAT ?= text
SEMGREP_OUTPUT ?=
_SEMGREP_OUT = $(if $(SEMGREP_OUTPUT),--output $(SEMGREP_OUTPUT),)

sast: ## Semgrep static analysis (pinned version + packs — reproducible local == CI)
	$(SEMGREP) scan \
		--config p/python \
		--config p/owasp-top-ten \
		--config p/security-audit \
		--error \
		--exclude tests/ \
		--exclude scripts/ \
		--exclude infra/ \
		--exclude-rule html.security.audit.missing-integrity.missing-integrity \
		$(if $(filter sarif,$(SEMGREP_FORMAT)),--sarif) \
		$(_SEMGREP_OUT)

# ───────────────────── Security scans (Trivy) ─────────────────────
# Single source of truth for Trivy — local, pre-commit, and CI run these.
# The binary version is PINNED for reproducibility + supply-chain safety (we
# never run a brand-new, unvetted release the moment it drops). The vulnerability
# DB is still fetched fresh every run, so CVE detection stays current. Upgrades
# flow through Dependabot (setup-trivy action SHA) with a cooldown window.
# CI installs this exact version via the pinned setup-trivy action; locally,
# scan-* fetches the pinned build into .tools/ if the trivy on PATH differs, so
# local runs match CI ("make updates first, like the pipeline").
# CI sets TRIVY_FORMAT=sarif + TRIVY_OUTPUT=<file> to emit SARIF for Code
# Scanning; the base-image reconcile sets TRIVY_IGNOREFILE= to scan unsuppressed.
TRIVY_VERSION ?= 0.72.0
TRIVY ?= trivy
TRIVY_FORMAT ?= table
TRIVY_OUTPUT ?=
TRIVY_IGNOREFILE ?= .trivyignore
TRIVY_IMAGE_EXIT ?= 1
TRIVY_SCANNERS ?=
_TRIVY_OUT = $(if $(TRIVY_OUTPUT),--output $(TRIVY_OUTPUT),)
_TRIVY_IGN = $(if $(TRIVY_IGNOREFILE),--ignorefile $(TRIVY_IGNOREFILE),)
_TRIVY_SCAN = $(if $(TRIVY_SCANNERS),--scanners $(TRIVY_SCANNERS),)

# Resolve a Trivy at exactly $(TRIVY_VERSION); install the pinned build into
# .tools/ when the one on PATH differs. Sets shell var $$T to the binary.
define _trivy
T="$(TRIVY)"; \
if [ "$$($$T --version 2>/dev/null | awk '/Version:/{print $$2; exit}')" != "$(TRIVY_VERSION)" ]; then \
  echo ">> Installing pinned Trivy v$(TRIVY_VERSION) into .tools/ (PATH trivy differs)"; \
  mkdir -p .tools; \
  curl -sfL "https://raw.githubusercontent.com/aquasecurity/trivy/v$(TRIVY_VERSION)/contrib/install.sh" | sh -s -- -b .tools "v$(TRIVY_VERSION)" >/dev/null; \
  T="./.tools/trivy"; \
fi
endef

scan-iac: ## Trivy IaC/config scan (infra/tofu) — advisory
	@$(_trivy); "$$T" config infra/tofu $(_TRIVY_IGN) --severity CRITICAL,HIGH,MEDIUM --exit-code 0 --format $(TRIVY_FORMAT) $(_TRIVY_OUT)

scan-fs: ## Trivy filesystem scan (deps + Dockerfiles, vulns only) — blocks on fixable CRITICAL/HIGH
	@$(_trivy); "$$T" fs . $(_TRIVY_IGN) --scanners vuln --severity CRITICAL,HIGH --ignore-unfixed --exit-code 1 --format $(TRIVY_FORMAT) $(_TRIVY_OUT)

scan-image: ## Trivy image scan (set IMAGE=...; TRIVY_IMAGE_EXIT=0 for advisory) — blocks on fixable CRITICAL/HIGH
	@$(_trivy); "$$T" image $(IMAGE) $(_TRIVY_IGN) $(_TRIVY_SCAN) --severity CRITICAL,HIGH --ignore-unfixed --exit-code $(TRIVY_IMAGE_EXIT) --format $(TRIVY_FORMAT) $(_TRIVY_OUT)

scan: scan-iac scan-fs ## Run repo Trivy scans (IaC + filesystem)

smoke: ## POST to /api/health/deep and exit non-zero if not healthy
	@FUNC_URL=$${FUNC_URL:-http://localhost:7071}; \
	echo "Smoke-checking $${FUNC_URL}/api/health/deep …"; \
	RESPONSE=$$(curl -sf "$${FUNC_URL}/api/health/deep" 2>/dev/null); \
	if [ -z "$$RESPONSE" ]; then echo "ERROR: /api/health/deep unreachable" >&2; exit 1; fi; \
	STATUS=$$(echo "$$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))"); \
	echo "Health status: $${STATUS}"; \
	if [ "$$STATUS" = "failing" ]; then echo "FAILED: health/deep reports failing" >&2; exit 1; fi; \
	echo "OK"

# ───────────────────── Cleanup ─────────────────────

clean: dev-down ## Stop Azurite and remove data volume
	docker volume rm kml-satellites_azurite-data 2>/dev/null || true
	@echo "Cleaned up."
