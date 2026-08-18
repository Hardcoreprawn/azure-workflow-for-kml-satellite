.PHONY: help setup dev-up dev-down dev-init \
       dev-all dev-logs dev-rebuild \
	test-upload ux-smoke test-fast test test-int test-int-live test-int-stripe test-pipeline-local real-acquisition-check blueprint-parity-check lint fmt check smoke clean prune-branches \
	_free-ports \
	sast scan scan-iac scan-fs scan-image lint-actions build-rust ci-local

SHELL  := /bin/bash
.DEFAULT_GOAL := help

# ───────────────────── Help ─────────────────────

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

# ───────────────────── Setup ─────────────────────

setup: ## Install Python deps (Docker required for the app stack — see dev-init/dev-all)
	uv sync --all-extras

# ───────────────────── Port cleanup ─────────────────────

DEV_FUNC_PORT := 7071
DEV_WEB_PORT := 4280
DEV_WEB_LEGACY_PORT := 1111
DEV_STORAGE_PORTS := 10000 10001 10002
DEV_WEB_PORTS := $(DEV_WEB_PORT) $(DEV_WEB_LEGACY_PORT)
DEV_PORTS := $(DEV_FUNC_PORT) $(DEV_WEB_PORTS) $(DEV_STORAGE_PORTS)

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
	docker compose up -d azurite
	@echo "Azurite running on localhost:10000 (blob), :10001 (queue), :10002 (table)"

dev-down: _free-ports ## Stop containers and free ports
	docker compose down

dev-init: dev-up ## Start Azurite + create storage containers
	uv run python scripts/init_storage.py

# ───────────────────── Full Stack ─────────────────────

# Resolved once per `make` invocation; empty outside a Docker-outside-of-
# Docker devcontainer, in which case docker-compose.yml/.override.yml fall
# back to "." (see scripts/detect_dood_workspace.sh).
DEV_WORKSPACE := $(shell bash scripts/detect_dood_workspace.sh)
export DEV_WORKSPACE

dev-all: _free-ports ## Full stack via docker-compose (Azurite + func + web) — the single local dev path
	@if [ -n "$(DEV_WORKSPACE)" ]; then echo "Detected Docker-outside-of-Docker — using host path $(DEV_WORKSPACE) for bind mounts"; fi
	source .github/image-config.env && export UV_VERSION && \
	docker compose down --remove-orphans 2>/dev/null || true
	source .github/image-config.env && export UV_VERSION && docker compose up --build -d
	@echo ""
	@echo "╔══════════════════════════════════════════════════════╗"
	@echo "║  All services starting via docker-compose:           ║"
	@echo "║                                                      ║"
	@echo "║  Website:    http://localhost:4280                    ║"
	@echo "║  Functions:  http://localhost:7071/api/health (compute)║"
	@echo "║  Orchestrator: http://localhost:7072/api/health        ║"
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

build-rust: ## Build + install the treesight_rs PyO3 extension into the active venv (needs a Rust toolchain; baked into the dev image)
	uv pip install --force-reinstall ./rust

test-upload: ## Upload sample KML and trigger pipeline
	uv run python scripts/simulate_upload.py

ux-smoke: ## UX smoke test across host site, EUDR/conservation/account apps, and the API auth boundary (needs make dev-all running + uv sync --extra ux)
	@uv run python -c "import playwright" 2>/dev/null || { echo "ERROR: playwright not installed. Run: uv sync --extra ux"; exit 1; }
	uv run playwright install chromium --with-deps 2>/dev/null || uv run playwright install chromium
	uv run python scripts/ux_journeys.py

# Freeze and export the raw value only for this target, never through a shell command.
test-fast: override export TESTS := $(value TESTS)
test-fast: ## Run targeted tests for the edit loop (requires TESTS="path-or-node")
	uv run python scripts/run_targeted_tests.py

test: ## Run unit tests (canonical — CI runs this exact command)
	uv run pytest tests/ -v -m "not integration" --tb=short --cov=treesight --cov-report=xml

test-int: ## Run integration tests against a running Azurite (creates containers first)
	uv run python scripts/init_storage.py
	uv run python scripts/run_integration_tests.py --marker integration_azurite tests/test_integration.py

test-int-live: ## Run integration smoke tests against Azurite + local Functions host
	uv run python scripts/run_integration_tests.py --marker integration_live_stack tests/test_pipeline_smoke_e2e.py tests/test_monster_aoi_scale.py

test-int-stripe: ## Run external Stripe integration tests (requires STRIPE_API_KEY)
	uv run python scripts/run_integration_tests.py --marker integration_external tests/test_integration_billing.py

test-pipeline-local: ## Unattended local/CI pipeline e2e gate against a running Azurite — no live Azure environment required (#1215)
	@command -v func >/dev/null 2>&1 || { echo "ERROR: func not found. Run: bash scripts/setup_func_tools.sh"; exit 1; }
	uv run python scripts/init_storage.py
	uv run python scripts/e2e_local.py

real-acquisition-check: ## Run real-world EUDR fixtures against the REAL Planetary Computer provider for manual review (#1379) — not a CI gate
	@command -v func >/dev/null 2>&1 || { echo "ERROR: func not found. Run: bash scripts/setup_func_tools.sh"; exit 1; }
	uv run python scripts/init_storage.py
	uv run python scripts/real_acquisition_runner.py

blueprint-parity-check: ## Verify compute and orchestrator serve the identical HTTP blueprint set (needs make dev-all running) (#1407)
	uv run python scripts/validate_blueprint_parity.py

lint: ## Static checks: ruff lint + format check + pyright (canonical — CI runs this)
	uv run ruff check .
	uv run ruff format --check .
	uv run pyright

fmt: ## Auto-format and autofix with ruff
	uv run ruff format .
	uv run ruff check --fix .

check: lint test ## Full local gate (lint + test) — identical to CI

ci-local: ## Run the gates inside the dev container image, exactly as CI does (#1086)
	bash scripts/ci_local.sh $(GATE)

# ───────────────────── GitHub Actions linting (actionlint) ─────────────────────
# Single source of truth for actionlint — local (pre-commit) and CI run this
# exact target, so the pinned version and the shellcheck rule suppressions live
# in one place and cannot drift. Mirrors the SEMGREP/TRIVY pattern. See #1080.
#
# actionlint feeds each `run:` script to shellcheck via stdin, so a repo-root
# .shellcheckrc is NOT honoured — the suppressions must be passed via
# SHELLCHECK_OPTS (verified). Keep them here, the only place:
#   SC2129 style-only (individual redirects vs a block); not a bug.
#   SC2016 false positive for our jq programs, which use single quotes so
#          `$var` refers to jq variables, not the shell.
ACTIONLINT_VERSION ?= 1.7.11
ACTIONLINT_DIR := $(HOME)/.cache/actionlint/$(ACTIONLINT_VERSION)
ACTIONLINT_BIN := $(ACTIONLINT_DIR)/actionlint
ACTIONLINT_SHELLCHECK_OPTS ?= -e SC2129 -e SC2016

lint-actions: ## Lint GitHub Actions workflows with pinned actionlint (canonical — CI runs this)
	@if [ ! -x "$(ACTIONLINT_BIN)" ]; then \
		echo "Installing actionlint $(ACTIONLINT_VERSION)…"; \
		mkdir -p "$(ACTIONLINT_DIR)"; \
		script="$$(mktemp)"; \
		curl -fsSL "https://raw.githubusercontent.com/rhysd/actionlint/v$(ACTIONLINT_VERSION)/scripts/download-actionlint.bash" -o "$$script"; \
		bash "$$script" "$(ACTIONLINT_VERSION)" "$(ACTIONLINT_DIR)"; \
		rm -f "$$script"; \
	fi
	SHELLCHECK_OPTS="$(ACTIONLINT_SHELLCHECK_OPTS)" "$(ACTIONLINT_BIN)" -color

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
TRIVY_VERSION ?= 0.73.0
TRIVY ?= trivy
TRIVY_FORMAT ?= table
TRIVY_OUTPUT ?=
TRIVY_IGNOREFILE ?= .trivyignore
TRIVY_IMAGE_EXIT ?= 1
TRIVY_SCANNERS ?=
TRIVY_SKIP_DIRS ?=
_TRIVY_OUT = $(if $(TRIVY_OUTPUT),--output $(TRIVY_OUTPUT),)
_TRIVY_IGN = $(if $(TRIVY_IGNOREFILE),--ignorefile $(TRIVY_IGNOREFILE),)
_TRIVY_SCAN = $(if $(TRIVY_SCANNERS),--scanners $(TRIVY_SCANNERS),)
_TRIVY_SKIP = $(foreach d,$(TRIVY_SKIP_DIRS),--skip-dirs $(d))

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

scan-image: ## Trivy image scan (set IMAGE=...; TRIVY_IMAGE_EXIT=0 for advisory; TRIVY_SKIP_DIRS="a b" to exclude bundled tool dirs) — blocks on fixable CRITICAL/HIGH
	@$(_trivy); "$$T" image $(IMAGE) $(_TRIVY_IGN) $(_TRIVY_SCAN) $(_TRIVY_SKIP) --severity CRITICAL,HIGH --ignore-unfixed --exit-code $(TRIVY_IMAGE_EXIT) --format $(TRIVY_FORMAT) $(_TRIVY_OUT)

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

prune-branches: ## Delete local branches whose upstream was deleted (merged/closed PRs)
	@git fetch --prune
	@gone=$$(git for-each-ref --format='%(refname:short) %(upstream:track)' refs/heads \
		| awk '$$2=="[gone]"{print $$1}'); \
	if [ -z "$$gone" ]; then \
		echo "No stale branches to prune."; \
	else \
		echo "$$gone" | xargs -r git branch -D; \
	fi
