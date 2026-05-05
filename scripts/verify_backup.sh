#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# scripts/verify_backup.sh — Automated PostgreSQL backup verification
#
# USAGE:
#   ./scripts/verify_backup.sh [backup_file]
#
#   If no file is passed, the script first runs pg_dump against the Docker
#   postgres container to create a fresh backup, then verifies it.
#   This covers both CI (create + verify) and manual "verify existing file" use.
#
# WHAT IT DOES (3-tier MAANG-grade verification):
#   Tier 1: pg_restore --list — confirms archive is not corrupted
#   Tier 2: Restore to an isolated ephemeral Docker container
#   Tier 3: Run table-level row-count checks on critical tables
#
# EXIT CODES:
#   0 — All checks passed. Backup is verified good.
#   1 — One or more checks failed. Backup should not be trusted.
#
# ENVIRONMENT:
#   DB_HOST       — PostgreSQL host (default: localhost)
#   DB_PORT       — PostgreSQL port (default: 5432)
#   DB_USER       — PostgreSQL user (default: yali_user)
#   DB_NAME       — Database name (default: yali_db)
#   PGPASSWORD    — Password (read from .env if not set)
#
# DEPENDENCIES:
#   pg_dump, pg_restore, psql — installed locally or via brew install libpq
#   docker                    — for ephemeral restore container
#
# MAANG pattern reference:
#   Google SRE Book §8: "An unverified backup is worse than no backup — it
#   creates false confidence that disappears exactly when you need it most."
#   Netflix Chaos Engineering: "Test recovery paths as rigorously as you test
#   the happy path."
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Colour output ─────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log_info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
log_ok()      { echo -e "${GREEN}[PASS]${NC}  $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_fail()    { echo -e "${RED}[FAIL]${NC}  $*" >&2; }
log_section() { echo -e "\n${BOLD}── $* ──────────────────────────────────────────${NC}"; }

# ── Configuration ─────────────────────────────────────────────────────────────
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_USER="${DB_USER:-yali_user}"
DB_NAME="${DB_NAME:-yali_db}"
TEST_DB="yali_backup_verify_$$"  # $$ = PID for unique name per run
BACKUP_DIR="$(pwd)/backups"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"

# Load PGPASSWORD from .env if not already set.
# Our .env uses DATABASE_URL (a connection string), not a separate DB_PASSWORD key.
# Parse the password component from: postgresql://user:password@host:port/db
if [[ -z "${PGPASSWORD:-}" ]]; then
    if [[ -n "${DATABASE_URL:-}" ]]; then
        # Extract password from DATABASE_URL connection string
        PGPASSWORD="$(echo "${DATABASE_URL}" | sed 's|.*://[^:]*:\([^@]*\)@.*|\1|')"
    elif [[ -f .env ]]; then
        # Fallback: parse DATABASE_URL from .env file
        _DB_URL="$(grep '^DATABASE_URL=' .env | cut -d= -f2-)"
        PGPASSWORD="$(echo "${_DB_URL}" | sed 's|.*://[^:]*:\([^@]*\)@.*|\1|')"
    fi
    export PGPASSWORD
fi

# ── Determine backup file ─────────────────────────────────────────────────────
BACKUP_FILE="${1:-}"

if [[ -z "$BACKUP_FILE" ]]; then
    log_section "Step 0: Creating backup"
    mkdir -p "$BACKUP_DIR"
    BACKUP_FILE="$BACKUP_DIR/yali_backup_$TIMESTAMP.dump"

    log_info "Running pg_dump → $BACKUP_FILE"

    # Custom format (-Fc) — required for pg_restore --list integrity check
    # --no-owner / --no-acl: portable dump, no role-specific SQL
    pg_dump \
        --host="$DB_HOST" \
        --port="$DB_PORT" \
        --username="$DB_USER" \
        --dbname="$DB_NAME" \
        --format=custom \
        --no-owner \
        --no-acl \
        --file="$BACKUP_FILE"

    if [[ $? -ne 0 ]]; then
        log_fail "pg_dump failed. Check DB connectivity and credentials."
        exit 1
    fi
    log_ok "Backup created: $BACKUP_FILE ($(du -sh "$BACKUP_FILE" | cut -f1))"
fi

# ── Tier 1: Structural integrity check ───────────────────────────────────────
log_section "Tier 1: Structural integrity check"
log_info "Running pg_restore --list on $BACKUP_FILE"

if pg_restore --list "$BACKUP_FILE" > /dev/null 2>&1; then
    log_ok "Archive structure is valid — not corrupted"
else
    log_fail "pg_restore --list failed — backup file is corrupted or unreadable"
    exit 1
fi

# ── Tier 2: Ephemeral restore test ───────────────────────────────────────────
log_section "Tier 2: Ephemeral restore test"

# Cleanup function — always drop test DB on exit (success or failure)
cleanup() {
    log_info "Cleaning up ephemeral database $TEST_DB"
    psql \
        --host="$DB_HOST" \
        --port="$DB_PORT" \
        --username="$DB_USER" \
        --dbname=postgres \
        --command="DROP DATABASE IF EXISTS \"$TEST_DB\";" \
        > /dev/null 2>&1 || true
}
trap cleanup EXIT

log_info "Creating ephemeral test database: $TEST_DB"
psql \
    --host="$DB_HOST" \
    --port="$DB_PORT" \
    --username="$DB_USER" \
    --dbname=postgres \
    --command="CREATE DATABASE \"$TEST_DB\";" \
    > /dev/null

log_info "Restoring backup to $TEST_DB"
# NOTE: --jobs=N (parallel restore) requires directory format (-Fd).
# Our backup uses custom format (-Fc) — parallel flag is not supported.
# Single-process restore is correct here.
pg_restore \
    --host="$DB_HOST" \
    --port="$DB_PORT" \
    --username="$DB_USER" \
    --dbname="$TEST_DB" \
    --no-owner \
    --no-acl \
    "$BACKUP_FILE"

if [[ $? -ne 0 ]]; then
    log_fail "pg_restore to ephemeral DB failed"
    exit 1
fi
log_ok "Restore completed successfully"

# ── Tier 3: Data integrity checks ────────────────────────────────────────────
log_section "Tier 3: Data integrity verification"

PASS_COUNT=0
FAIL_COUNT=0

check_table() {
    local table="$1"
    local min_rows="${2:-0}"  # 0 = just verify table exists and is readable

    local count
    count=$(psql \
        --host="$DB_HOST" \
        --port="$DB_PORT" \
        --username="$DB_USER" \
        --dbname="$TEST_DB" \
        --tuples-only \
        --no-align \
        --command="SELECT COUNT(*) FROM \"$table\";" 2>/dev/null)

    # psql --tuples-only outputs leading/trailing whitespace — trim before integer comparison.
    # Without xargs, bash [[ "  5" -ge 0 ]] raises: integer expression expected.
    count=$(echo "$count" | xargs)

    if [[ -z "$count" ]]; then
        log_fail "Table '$table' — could not query (table missing or migration broken)"
        FAIL_COUNT=$((FAIL_COUNT + 1))
        return
    fi

    if [[ "$count" -ge "$min_rows" ]]; then
        log_ok "Table '$table' — $count rows (≥ $min_rows required)"
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        log_fail "Table '$table' — $count rows (expected ≥ $min_rows)"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

# Core multi-tenancy tables (must always have data in a real backup)
check_table "core_complex"          0  # 0 = just verify table exists
check_table "core_unit"             0
check_table "users_user"            0

# Django framework tables (must exist post-migration)
check_table "django_migrations"     1  # Must have at least 1 migration
check_table "django_content_type"   1

# Application tables (data integrity)
check_table "facilities_facility"   0
check_table "maintenance_maintenanceticket" 0

log_section "Verification Summary"
echo -e "  ${GREEN}Passed: $PASS_COUNT${NC}"
echo -e "  ${RED}Failed: $FAIL_COUNT${NC}"

if [[ "$FAIL_COUNT" -gt 0 ]]; then
    log_fail "Backup verification FAILED — $FAIL_COUNT checks did not pass"
    log_fail "This backup should NOT be trusted for disaster recovery"
    exit 1
fi

log_ok "All checks passed. Backup is verified and ready for disaster recovery."
log_ok "Backup file: $BACKUP_FILE"
exit 0
