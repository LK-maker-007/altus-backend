# Yali Backend

**Production-grade Django REST API** for the Yali apartment management platform.

**Repo:** `yali-platform/yali-backend`
**Companion:** [`yali-app`](../yali-app) — Expo React Native mobile application

---

## Stack

| Layer | Technology |
|---|---|
| Language | Python 3.14 |
| Framework | Django 6.0 + Django REST Framework |
| Database | PostgreSQL 16 with GiST exclusion constraints + Row-Level Security |
| Cache / Queue | Redis 7.4 + Celery |
| Storage | Cloudflare R2 (photos, documents) |
| Auth | Custom JWT (stateless, phone + OTP) |
| Container | Docker Compose — postgres + redis + django api + celery worker + celery beat |

---

## Quick Start (local dev)

### Prerequisites
- Python 3.14
- Docker Desktop (running)
- `make`
- `k6` (for load tests) — `brew install k6`

### One-time setup

```bash
# 1. Clone and enter
git clone <repo-url> yali-backend && cd yali-backend

# 2. Create virtualenv + install deps (needed for make test, make lint on host)
python3 -m venv .venv && .venv/bin/pip install -r requirements/development.txt

# 3. Copy env and fill in secrets
cp .env.example .env          # Edit JWT_SECRET_KEY, QR_TOKEN_SECRET etc.

# 4. Build images (first time only — ~2 min)
make build

# 5. Start everything — postgres, redis, django, celery worker, celery beat
#    Migrations run automatically inside the api container.
make up
```

That's it. API is live at **http://localhost:8000**.

### Running on host (for pdb breakpoints)

```bash
# Docker postgres + redis must be running (make up)
make dev-host    # Django on host → http://localhost:8000
make worker      # Celery worker on host
```

### Django Admin (browser)

Navigate to **http://127.0.0.1:8000/admin/** after `make dev` is running.

**Dev superuser (pre-created):**
```
Phone: +919000099999
Password: admin123
```

---

## Running Tests

```bash
# Full test suite (requires Docker Postgres running)
make test

# Run a specific test file
make test-file FILE=tests/test_bookings/test_hold.py

# Parallel execution (faster)
make test-fast

# With verbose output and no fail-fast
pytest --tb=short -v -p no:randomly
```

**Test DB:** `yali_test` — created automatically by pytest-django. Extensions
(`btree_gist`, `uuid-ossp`, `pgcrypto`) are pre-installed in `template1` via
`docker/postgres/init/01_extensions.sql`.

---

## Makefile Commands

See [COMMANDS.md](./COMMANDS.md) for the complete reference.

| Command | Description |
|---|---|
| `make up` | Start full stack — postgres + redis + api + worker + beat (migrations auto-run) |
| `make down` | Stop all containers |
| `make down-v` | Stop + wipe database volumes (fresh start) |
| `make build` | Rebuild Docker images (after requirements change) |
| `make logs` | Tail all container logs |
| `make logs-api` | Tail Django API logs |
| `make logs-worker` | Tail Celery worker logs |
| `make migrate` | Run migrations on HOST (Docker postgres must be up) |
| `make migrate-docker` | Run migrations inside the running api container |
| `make makemigrations` | Create new migration files (on host) |
| `make dev-host` | Start Django on HOST (for pdb/debugger) |
| `make test` | Run full pytest suite |
| `make gate` | Full quality gate: fmt + lint + test (run before every PR) |
| `make shell` | Django shell (host) |
| `make psql` | PostgreSQL shell inside container |
| `make health-check` | Probe `GET /api/v1/health/` and print JSON status |
| `make backup-verify` | pg_dump + 3-tier backup verification (Tier1: integrity, Tier2: restore, Tier3: data) |
| `make create-load-test-user` | Create deterministic k6 test user in dev DB (prerequisite for load tests) |
| `make load-test-smoke` | k6 smoke test — 5 VUs, 20s (CI-safe) |
| `make load-test` | k6 full load — staging only, never production |

---

## Architecture

```
config/           ← Django settings (base / development / test / production)
apps/
  users/          ← Auth: registration, OTP, JWT, profile
  bookings/       ← Facility booking: hold, confirm, cancel (GiST concurrency)
  facilities/     ← Facility catalogue + slot availability
  visitors/       ← Visitor pre-registration + gate OTP
  maintenance/    ← Maintenance tickets + photo upload
  packages/       ← Package delivery notification
  community/      ← Announcements, lost & found
  emergency/      ← Emergency alerts
  security/       ← Security staff actions
  dashboard/      ← Resident dashboard aggregation
  core/           ← Shared models (Complex, Unit)
tests/
  factories/      ← factory_boy factories for all models
  test_auth/      ← Auth flow tests (US-001 → US-007)
  test_bookings/  ← Booking + concurrency tests (US-008 → US-012)
  test_visitors/  ← Visitor gate pass tests (US-013 → US-015)
  test_maintenance/ ← Ticket lifecycle tests (US-019 → US-027)
  test_middleware/ ← RLS multi-tenancy tests (security-critical)
  test_facilities/ ← Slot computation tests
docker/
  postgres/init/  ← 01_extensions.sql — btree_gist, uuid-ossp, pgcrypto
```

---

## Key Design Decisions

- **No ORM multi-tenancy plugins** — RLS is enforced at middleware level via `ComplexContextMiddleware` + scoped managers. Each request sees only its complex's data.
- **GiST exclusion constraint** — double-booking prevention is enforced at DB level (`bookings.0003`), not just application level. The constraint fires even if application code is bypassed.
- **`select_for_update(nowait=True)`** — pessimistic locking on booking hold creation. Concurrent requests raise `SlotUnavailableError` immediately rather than waiting.
- **`transaction.on_commit()`** — all Celery task dispatches are deferred to post-commit. No task fires on rollback.
- **Class-based service layer** — all business logic lives in `services.py`, never in `models.save()` or views (ADR-010).

---

## Docs

Architecture, API contracts, DB schema, and coding standards live in the Obsidian vault:

```
native-vault/
  docs/
    architecture/
    api-contracts/
    database-schema.md
    local-dev-setup.md
    testing-strategy.md
```
