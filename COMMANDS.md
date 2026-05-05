# Yali Backend — Command Reference

All commands assume you are in the `yali-backend/` directory.
Run `source .venv/bin/activate` before running any Python/Django commands.

---

## Infrastructure (Docker)

| Command | What it does |
|---|---|
| `make up` | Start full stack — postgres + redis + api + worker + beat |
| `make build` | Rebuild Docker images (run after requirements change) |
| `make down` | Stop containers (keep data volumes) |
| `make down-v` | Stop containers AND delete data volumes (full reset) |
| `make logs` | Tail logs for all containers |
| `make logs-api` | Tail Django API logs only |
| `make logs-worker` | Tail Celery worker logs only |
| `make logs-pg` | Tail postgres logs only |
| `make logs-redis` | Tail redis logs only |
| `make psql` | Open psql shell into `yali_db` as `yali_user` |

### Manual Docker commands

```bash
# Start
docker compose up -d --build

# Stop (keep data)
docker compose down

# Full reset (delete all DB data and re-run init SQL)
docker compose down -v && docker compose up -d

# Check health
docker compose ps

# View postgres logs
docker compose logs postgres -f

# Open psql directly
docker compose exec postgres psql -U yali_user -d yali_db

# Open redis-cli directly
docker compose exec redis redis-cli
```

---

## Database Migrations

```bash
# Apply all pending migrations
make migrate
# or
python manage.py migrate

# Create a new migration after model changes
python manage.py makemigrations <app_name>
# Example:
python manage.py makemigrations bookings

# Show migration plan (dry run)
python manage.py migrate --plan

# Show all migrations and their status
python manage.py showmigrations

# Revert a specific migration
python manage.py migrate <app_name> <migration_number>
# Example (revert bookings to before 0003):
python manage.py migrate bookings 0002

# Squash migrations (do NOT do this if already deployed)
python manage.py squashmigrations <app_name> <from> <to>
```

---

## Development Server

```bash
# Recommended: Docker for infra, Django on host (hot reload + pdb)
make up          # starts postgres + redis + worker + beat
make dev-host    # starts Django on host → http://localhost:8000
# or directly:
python manage.py runserver localhost:8000

# Start on a different port
python manage.py runserver localhost:8001

# Start Celery worker (separate terminal, if not using make up)
celery -A config.celery worker --loglevel=info

# Start Celery beat scheduler (separate terminal, if not using make up)
celery -A config.celery beat --loglevel=info
```

**Dev server URLs:**
- API root: http://localhost:8000/api/v1/
- Django Admin: http://localhost:8000/admin/
- Swagger UI: http://localhost:8000/api/schema/ui/
- OpenAPI YAML: http://localhost:8000/api/schema/

---

## Django Admin

### Create superuser

```bash
make superuser
# or
python manage.py createsuperuser --phone_number=+91XXXXXXXXXX
```

**Pre-created dev superuser** (created via `make superuser` on first setup):
```
Phone:    +919000099999
Password: admin123
URL:      http://127.0.0.1:8000/admin/
```

> ⚠️ These credentials are for local development only. Never use in production.

---

## Testing

```bash
# Full suite (fail-fast, randomised order)
make test
# or
pytest

# Full suite without fail-fast (see all failures)
pytest --no-header -q --tb=line -p no:randomly

# Specific file
pytest tests/test_bookings/test_hold.py -v

# Specific class
pytest tests/test_bookings/test_hold.py::TestHoldCreation -v

# Specific test
pytest tests/test_bookings/test_hold.py::TestHoldCreation::test_create_hold_returns_hold_status -v

# Parallel (fastest — uses all CPU cores)
make test-fast
# or
pytest -n auto

# With coverage report
pytest --cov=apps --cov-report=html
open htmlcov/index.html

# Re-use existing test DB (skip recreation)
pytest --reuse-db

# Keep test DB after run (useful for debugging test failures)
pytest --keepdb

# Show SQL queries executed during tests
pytest --ds=config.settings.test -s -v --log-cli-level=DEBUG
```

### Test environment notes

- **Test DB**: `yali_test` (auto-created by pytest-django)
- **Extensions**: `btree_gist`, `uuid-ossp`, `pgcrypto` inherited from `template1`
- **Celery**: always eager (`CELERY_TASK_ALWAYS_EAGER=True`) — tasks run synchronously
- **SMS**: mock provider — Twilio is never called
- **Concurrency tests**: must use `@pytest.mark.django_db(transaction=True)`

---

## Code Quality

```bash
# Lint (ruff)
ruff check .

# Format (ruff)
ruff format .

# Type check (mypy)
mypy apps/

# All checks at once
make lint

# Auto-fix lint issues
ruff check . --fix

# Full quality gate — fmt + lint + type-check + deploy-check + test (run before every PR)
make gate

# Deploy check (OpenAPI schema warnings + Django security config)
# Must return: "System check identified no issues (0 silenced)."
SECRET_KEY="ci-check-only-not-real-do-not-use-in-production-x99z" \
DATABASE_URL="postgresql://yali_app:ci@localhost:5432/ci" \
python manage.py check --deploy --settings=config.settings.production --fail-level WARNING
```

---

## Infrastructure Verification

These commands prove the infrastructure works — not just that the scripts exist.

### Health check

```bash
# Probe /api/v1/health/ — Django server must be running (make dev-host)
make health-check
# or
curl -s http://localhost:8000/api/v1/health/ | python3 -m json.tool
# Expected: {"status": "ok", "database": "ok", "cache": "ok"}

# Check OpenAPI schema loads without warnings
curl -s http://localhost:8000/api/schema/ | head -5
# Expected: openapi: 3.0.3 ...
```

### Backup verification (3-tier)

```bash
# Requires: Docker postgres running (make up), pg_dump installed (brew install libpq)
make backup-verify
```

What it does:
1. **Tier 1** — `pg_restore --list`: confirms archive is not corrupted
2. **Tier 2** — Ephemeral restore: creates a temp DB, restores, drops on exit
3. **Tier 3** — Row-count checks: verifies critical tables are readable

Exit code `0` = backup is verified good. Exit code `1` = do not trust this backup.

### k6 load testing

```bash
# Prerequisites:
#   1. k6 installed:              brew install k6
#   2. Stack running:             make up && make dev-host
#   3. Load test user created:    make create-load-test-user

# Smoke test — 5 VUs, 20 seconds (CI-safe, runs on every PR)
make load-test-smoke
# or
k6 run load-tests/k6/smoke.js

# Full load scenario — ramping arrival-rate, 10 minutes
# WARNING: Run against staging only. Never against production.
make load-test
```

### Load test user

```bash
# Create the deterministic test user required by k6's auth flow.
# Must run once after `make migrate`. Idempotent — safe to run again.
make create-load-test-user
# or
python manage.py create_load_test_user

# Dry run — prints what would be created without writing to DB
python manage.py create_load_test_user --dry-run

# Custom phone number
python manage.py create_load_test_user --phone +919000012345
```

**Why this exists:** k6's `setup()` authenticates via `POST /api/v1/auth/login/`, which
calls `UserService.get_or_create_for_login()`. That method raises `RegistrationFailedError`
if the phone number has no account in the **real** DB. pytest factories are rolled back
after each test — they never persist to the dev DB. This command creates the user permanently.

**Safety guards:** Refuses to run if `SMS_PROVIDER != mock` or `DEBUG=False`
(use `--force` for staging). Never creates ghost accounts against real Twilio.

---

## Django Shell

```bash
# Interactive shell (IPython if available)
make shell
# or
python manage.py shell

# Run a one-off script
python manage.py shell -c "
from apps.bookings.models import Booking, BookingStatus
print(Booking.objects.filter(status=BookingStatus.HOLD).count(), 'active holds')
"

# Database shell (SQL)
python manage.py dbshell
```

---

## Environment Variables

```bash
# Check all required env vars are set
python scripts/check_env.py

# See current effective settings
python manage.py diffsettings

# Print DATABASE_URL being used
python -c "import os; print(os.environ.get('DATABASE_URL', 'not set'))"
```

### Required `.env` keys

| Variable | Description |
|---|---|
| `SECRET_KEY` | Django secret key |
| `JWT_SECRET_KEY` | JWT signing secret |
| `QR_TOKEN_SECRET` | QR registration token HMAC secret |
| `DATABASE_URL` | `postgresql://yali_user:yali_password@localhost/yali_db` |
| `REDIS_URL` | `redis://localhost:6379/0` |
| `SMS_PROVIDER` | `twilio` (production) or `mock` (local) |
| `TWILIO_ACCOUNT_SID` | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | Twilio auth token |
| `TWILIO_VERIFY_SERVICE_SID` | Twilio Verify service SID |
| `R2_ACCOUNT_ID` | Cloudflare R2 account ID |
| `R2_ACCESS_KEY_ID` | R2 access key |
| `R2_SECRET_ACCESS_KEY` | R2 secret key |
| `R2_ENDPOINT_URL` | R2 endpoint URL |
| `R2_PUBLIC_URL` | Public media base URL |

---

## Useful One-liners

```bash
# Count all bookings by status
python manage.py shell -c "
from apps.bookings.models import Booking, BookingStatus
for s in BookingStatus:
    n = Booking.objects.filter(status=s).count()
    print(f'{s}: {n}')
"

# List all registered complexes
python manage.py shell -c "
from apps.core.models import Complex
for c in Complex.objects.all(): print(c.id, c.name, c.slug)
"

# Check postgres extension list
docker compose exec postgres psql -U yali_user -d yali_db -c "SELECT extname, extversion FROM pg_extension ORDER BY extname;"

# Check template1 extensions (inherited by test DB)
docker compose exec postgres psql -U yali_user -d template1 -c "SELECT extname FROM pg_extension;"

# Flush Redis cache
docker compose exec redis redis-cli FLUSHDB

# Tail celery task logs
celery -A config.celery events --dump

# Verify DB connectivity
python manage.py check --database default
```
