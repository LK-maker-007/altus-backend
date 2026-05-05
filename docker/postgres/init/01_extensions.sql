-- docker/postgres/init/01_extensions.sql
--
-- PostgreSQL initialisation — executed once on first container start.
-- Mounted at: /docker-entrypoint-initdb.d/01_extensions.sql (read-only)
--
-- Three things this script does:
--   1. Grant CREATEDB to yali_user so pytest-django can create yali_test
--   2. Install extensions into template1 so ALL databases (incl. yali_test)
--      inherit them automatically on creation
--   3. Install extensions into yali_db for good measure
--
-- See docs/local-dev-setup.md §7.4 for full rationale.
-- See docs/database-schema.md §4 for btree_gist requirement.

-- ── 1. Grant CREATEDB to the application user ─────────────────────────────────
-- pytest-django creates the test database (yali_test) by calling
-- CREATE DATABASE. It connects as yali_user, which must have CREATEDB
-- privilege. Without this, pytest fails with:
--   ERROR:  permission denied to create database
ALTER ROLE yali_user CREATEDB;

-- ── 2. Install extensions into template1 ──────────────────────────────────────
-- Every new database created with CREATE DATABASE inherits all objects from
-- template1. Installing extensions here means yali_test (created by pytest)
-- gets btree_gist automatically — without needing a separate CREATE EXTENSION
-- step after the test database is created.
--
-- Connect to template1 to install there.
\connect template1

-- btree_gist: REQUIRED for the GiST exclusion constraint on bookings_booking:
--   EXCLUDE USING GIST (facility_id WITH =, tstzrange(...) WITH &&)
--   WHERE (status = 'confirmed');
-- Ships with PostgreSQL core — no additional packages needed.
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- uuid-ossp: provides uuid_generate_v4(). Included for raw SQL / admin tooling
-- compatibility. Django 6 uses gen_random_uuid() (pgcrypto) by default.
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- pgcrypto: provides gen_random_uuid() used by Django 6 UUID field defaults.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ── 3. Install extensions into yali_db (dev database) ────────────────────────
\connect yali_db

CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pgcrypto;
