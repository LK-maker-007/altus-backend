# Yali Backend — Developer Makefile
#
# ONE COMMAND to start everything:  make up
#   Starts: postgres + redis + django api + celery worker + celery beat
#   Migrations run automatically inside the api container on startup.
#
# To run Django on HOST (for debugger/breakpoints): make dev-host
# See docs/local-dev-setup.md for full local setup sequence.

.DEFAULT_GOAL := help
.PHONY: help build up down down-v logs logs-api logs-worker logs-beat logs-pg \
        logs-redis migrate makemigrations migrate-check migrate-docker psql \
        dev dev-host shell worker beat test test-v test-cov test-fast \
        test-serial test-concurrency test-rls lint fmt gate check-env \
        backup-verify health-check load-test-smoke load-test create-load-test-user \
        seed seed-reset

# ── Python / tool paths ───────────────────────────────────────────────────────
# WHY .venv/bin/python (not `python` or `python3`):
#   On macOS, `python` is not in PATH by default. `python3` is the system
#   interpreter, not the project venv. Pointing directly to the venv binary
#   means `make migrate`, `make test`, etc. work without `source .venv/bin/activate`.
PYTHON  := .venv/bin/python
PYTEST  := .venv/bin/pytest
CELERY  := .venv/bin/celery
BLACK   := .venv/bin/black
RUFF    := .venv/bin/ruff
MYPY    := .venv/bin/mypy
MANAGE  := $(PYTHON) manage.py

# ── Colours ───────────────────────────────────────────────────────────────────
BOLD  := \033[1m
RESET := \033[0m
GREEN := \033[32m
CYAN  := \033[36m
RED   := \033[31m

# ── Help ──────────────────────────────────────────────────────────────────────
help: ## Show this help message
	@echo ""
	@echo "$(BOLD)Yali Backend — available targets$(RESET)"
	@echo ""
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ { \
		printf "  $(CYAN)%-18s$(RESET) %s\n", $$1, $$2 \
	}' $(MAKEFILE_LIST)
	@echo ""

# ── Infrastructure ────────────────────────────────────────────────────────────
build: ## Build Django/Celery Docker images (run after requirements change)
	docker compose build
	@echo "$(GREEN)Images built.$(RESET)"

up: ## Start full stack — postgres + redis + api + worker + beat (migrations auto-run)
	docker compose up -d
	@echo "$(GREEN)Full stack up.$(RESET) API: http://localhost:8000 | DB: 5432 | Redis: 6379"
	@echo "$(CYAN)Logs:$(RESET) make logs | make logs-api | make logs-worker"

down: ## Stop containers (preserve volumes)
	docker compose down

down-v: ## Stop containers AND wipe all volumes (fresh database)
	docker compose down -v
	@echo "$(RED)All volumes deleted.$(RESET) Run 'make up' to reinitialise (migrations run automatically)."

logs: ## Tail all container logs
	docker compose logs -f

logs-api: ## Tail Django API logs only
	docker compose logs -f api

logs-worker: ## Tail Celery worker logs only
	docker compose logs -f worker

logs-beat: ## Tail Celery beat logs only
	docker compose logs -f beat

logs-pg: ## Tail postgres logs only
	docker compose logs -f postgres

logs-redis: ## Tail redis logs only
	docker compose logs -f redis

# ── Database ──────────────────────────────────────────────────────────────────
migrate: ## Run migrations on HOST against localhost:5432 (Docker postgres must be up)
	$(MANAGE) migrate

makemigrations: ## Create new migration files
	$(MANAGE) makemigrations

migrate-check: ## Verify no unapplied migrations (use in CI)
	$(MANAGE) migrate --check

migrate-docker: ## Run migrations inside the running api container
	docker compose exec api python manage.py migrate

psql: ## Open psql shell in the running postgres container
	docker compose exec postgres psql -U yali_user -d yali_db

# ── Application (host) ────────────────────────────────────────────────────────
dev-host: ## Run Django on HOST — useful for pdb breakpoints (Docker postgres+redis must be up)
	@echo "$(CYAN)Django on host → http://localhost:8000$(RESET)"
	$(MANAGE) runserver 0.0.0.0:8000

dev: dev-host ## Alias for dev-host

shell: ## Open Django shell (host)
	$(MANAGE) shell

worker: ## Start Celery worker on HOST (queues: default, notifications)
	$(CELERY) -A config worker --loglevel=info --queues default,notifications

beat: ## Start Celery beat on HOST
	$(CELERY) -A config beat --loglevel=info \
		--scheduler django_celery_beat.schedulers:DatabaseScheduler

# ── Testing ───────────────────────────────────────────────────────────────────
test: ## Run full test suite
	$(PYTEST)

test-v: ## Run tests with verbose output
	$(PYTEST) -v

test-cov: ## Run tests with coverage report
	$(PYTEST) --cov=apps --cov-report=term-missing --cov-fail-under=80

test-fast: ## Run tests in parallel across all CPU cores
	$(PYTEST) -n auto

test-serial: ## Run tests serially (debug parallel failures)
	$(PYTEST) -p no:randomly

test-concurrency: ## Run concurrency + exclusion constraint tests
	$(PYTEST) tests/test_bookings/test_concurrency.py tests/test_bookings/test_exclusion_constraint.py -v

test-rls: ## Run RLS cross-tenant isolation tests
	$(PYTEST) tests/test_middleware/ -v

# ── Code quality ──────────────────────────────────────────────────────────────
lint: ## Run black --check + ruff + mypy (read-only)
	$(BLACK) --check .
	$(RUFF) check .
	# WHY rm -rf .mypy_cache before mypy:
	#   mypy's cache format is version-specific. If the cache was written by a
	#   different mypy version (e.g. after `pip install --upgrade`), mypy 1.20
	#   crashes with "INTERNAL ERROR — NewSemanalDjangoPlugin" when it tries to
	#   deserialize incompatible cache files. Clearing the cache before every
	#   lint run costs ~0.5s but makes mypy deterministic across upgrades.
	#   Source: django-stubs README §mypy crashes + mypy issue #15712.
	rm -rf .mypy_cache
	$(MYPY) apps/ config/ manage.py --ignore-missing-imports

fmt: ## Auto-format: black + ruff --fix
	$(BLACK) .
	$(RUFF) check . --fix

gate: ## Full quality gate: fmt + lint + test (run before every PR)
	$(MAKE) fmt
	$(MAKE) lint
	$(MAKE) test

# ── Environment ───────────────────────────────────────────────────────────────
check-env: ## Validate environment variables
	$(PYTHON) scripts/check_env.py

# ── Backup Verification ───────────────────────────────────────────────────────────
# WHY automated backup verification:
#   Google SRE: "An unverified backup is worse than no backup."
#   MAANG standard: backup integrity is verified at three tiers:
#   1. pg_restore --list (structural integrity)
#   2. Ephemeral restore test (DB is actually restorable)
#   3. Table row-count checks (data was not corrupted)
backup-verify: ## Create pg_dump and run 3-tier verification (Tier1:integrity Tier2:restore Tier3:data)
	@echo "$(CYAN)Running 3-tier backup verification...$(RESET)"
	chmod +x scripts/verify_backup.sh
	# Source .env so DATABASE_URL is available for PGPASSWORD extraction
	@set -a && . ./.env && set +a && ./scripts/verify_backup.sh

# ── Health Check ───────────────────────────────────────────────────────────────
health-check: ## Probe GET /api/v1/health/ and print status (server must be running)
	@curl -sf http://localhost:8000/api/v1/health/ | python3 -m json.tool || \
		(echo "$(RED)Health check failed — is the server running? (make dev-host)$(RESET)" && exit 1)

# ── Load Testing ───────────────────────────────────────────────────────────────
# WHY k6 (not Locust):
#   - arrival-rate executor matches how we think (req/s not VU count)
#   - SLO thresholds make CI fail when latency degrades
#   - Native Grafana integration (observability already in Sentry)
#   - No Python dependency: k6 is a standalone binary
#
# PREREQUISITE: k6 must be installed — brew install k6
load-test-smoke: ## k6 smoke test — 5 VUs, 20s (run in CI on every PR)
	@command -v k6 > /dev/null 2>&1 || \
		(echo "$(RED)k6 not found. Install: brew install k6$(RESET)" && exit 1)
	@echo "$(CYAN)Running k6 smoke test (5 VUs, 20s)...$(RESET)"
	@echo "$(CYAN)Ensure Django is running: make dev-host$(RESET)"
	k6 run load-tests/k6/smoke.js

load-test: ## k6 full load scenario — ramping arrival-rate, 10 minutes (staging only)
	@command -v k6 > /dev/null 2>&1 || \
		(echo "$(RED)k6 not found. Install: brew install k6$(RESET)" && exit 1)
	@echo "$(RED)WARNING: Run against staging only. Do NOT run against production.$(RESET)"
	@echo "$(CYAN)Running full load scenario (10 minutes)...$(RESET)"
	k6 run load-tests/k6/scenarios.js

# ── Load Test User ─────────────────────────────────────────────────────────────
# Creates the deterministic test user required by k6's setup() auth flow.
# Must be run once after `make migrate` before running `make load-test-smoke`.
# Idempotent: safe to run multiple times.
create-load-test-user: ## Create k6 load test user in dev DB (prerequisite for load-test-smoke)
	@echo "$(CYAN)Creating load test user for k6 (SMS_PROVIDER=mock required)...$(RESET)"
	$(PYTHON) manage.py create_load_test_user

# ── Demo Data Seeding ──────────────────────────────────────────────────────────
# Creates a full demo apartment complex with residents, facilities, bookings,
# visitors, maintenance tickets, and announcements for manual testing.
# Idempotent: skips existing rows — safe to run multiple times.
seed: ## Seed dev DB with demo data (idempotent — skips existing rows)
	@echo "$(CYAN)Seeding demo data...$(RESET)"
	$(PYTHON) manage.py seed_demo_data

seed-reset: ## Wipe and re-seed all demo data (full reset)
	@echo "$(RED)Resetting and re-seeding demo data...$(RESET)"
	$(PYTHON) manage.py seed_demo_data --reset
