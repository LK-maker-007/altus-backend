# Secrets Rotation Runbook

**Applies to:** Yali Backend (yali-backend)
**Last updated:** 2026-04-28
**Status:** Active

---

> [!IMPORTANT]
> This runbook covers **zero-downtime** rotation for all production secrets.
> Each section is self-contained. Read the entire section before starting.
> Every rotation must be logged in the team audit trail with timestamp and operator name.

---

## Table of Contents

1. [JWT_SECRET_KEY (App signing key for user tokens)](#1-jwt_secret_key)
2. [SECRET_KEY (Django's internal signing key)](#2-secret_key)
3. [QR_TOKEN_SECRET (QR gate pass signing key)](#3-qr_token_secret)
4. [DATABASE_URL Password](#4-database_url-password)
5. [TWILIO Credentials](#5-twilio-credentials)
6. [Cloudflare R2 Credentials](#6-cloudflare-r2-credentials)
7. [Post-Rotation Verification Checklist](#7-post-rotation-verification-checklist)
8. [Emergency: Immediate Revocation](#8-emergency-immediate-revocation)

---

## 1. JWT_SECRET_KEY

**What it protects:** Signs and verifies every access and refresh token issued to mobile app users.  
**Risk if compromised:** An attacker can forge valid tokens for any user ID.  
**Recommended rotation period:** Every 90 days (or immediately on suspected compromise).  
**Zero-downtime:** ✅ Supported via `JWT_PREVIOUS_SECRET_KEY`.

### How zero-downtime rotation works

`apps/core/jwt_utils.decode_jwt()` tries `JWT_SECRET_KEY` first, then `JWT_PREVIOUS_SECRET_KEY` (if set). Only `InvalidSignatureError` triggers the fallback — expired/malformed tokens are rejected immediately regardless of which key is set. This mirrors Django's own `SECRET_KEY_FALLBACKS` pattern (Django 4.1+).

### Rotation steps

```bash
# On the production server
python manage.py rotate_jwt_secret
```

The command prints a new key and step-by-step instructions. Follow them exactly:

**Step 1 — Enable overlap window (no code change, env change only):**
```env
JWT_PREVIOUS_SECRET_KEY=<current value of JWT_SECRET_KEY>
```
Deploy. Both keys are now accepted for token verification. No users are affected.

**Step 2 — Switch signing key:**
```env
JWT_SECRET_KEY=<new key from manage.py rotate_jwt_secret>
```
Deploy. New tokens are signed with the new key. Old tokens (signed with the previous key) are still accepted via the fallback.

**Step 3 — Monitor:**
Watch Sentry auth error rate for 5 minutes post-deploy. A spike in `401` errors means tokens from the previous key are being rejected — check that `JWT_PREVIOUS_SECRET_KEY` is set correctly.

**Step 4 — Remove old key (after 30 days):**
After `JWT_REFRESH_TOKEN_LIFETIME_DAYS` (default: 30 days), all tokens signed with the old key have naturally expired.
```env
JWT_PREVIOUS_SECRET_KEY=   # empty
```
Deploy. Verify with:
```bash
python manage.py rotate_jwt_secret --verify
```

> [!CAUTION]
> **Never skip Step 1.** Setting `JWT_SECRET_KEY` to a new value without first setting `JWT_PREVIOUS_SECRET_KEY` will immediately invalidate every active session. All users are logged out simultaneously.

---

## 2. SECRET_KEY

**What it protects:** Django Admin sessions, CSRF tokens, password reset links, signed cookies.  
**Risk if compromised:** Admin session forgery, CSRF bypass, password reset link forgery.  
**Recommended rotation period:** Every 90 days.  
**Zero-downtime:** ✅ Supported via `SECRET_KEY_FALLBACKS` (Django 4.1+).

### Rotation steps

**Step 1 — Enable fallback:**
```env
SECRET_KEY_FALLBACKS=<current value of SECRET_KEY>
```
Deploy. Django accepts sessions signed with either key.

**Step 2 — Switch signing key:**
Generate a new key:
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```
```env
SECRET_KEY=<new value>
```
Deploy. New sessions use the new key. Admin users with existing sessions stay logged in until the old session expires.

**Step 3 — Remove fallback (after Django session TTL):**
Default Django session lifetime is 2 weeks (`SESSION_COOKIE_AGE = 1209600`).
After 2 weeks, all old sessions have expired.
```env
SECRET_KEY_FALLBACKS=   # empty
```
Deploy.

---

## 3. QR_TOKEN_SECRET

**What it protects:** HMAC signatures on QR registration tokens issued by `QRTokenService`.  
**Risk if compromised:** An attacker can forge QR codes that bypass complex/unit validation at registration.  
**Recommended rotation period:** Every 90 days, or when QR codes are bulk-reprinted.  
**Zero-downtime:** ⚠️ **NOT supported.** Rotating this key immediately invalidates all distributed QR codes.

### Rotation steps

**Step 1 — Communicate.**
Notify complex admins that existing QR codes will stop working after the rotation.
Set a rotation date with at least 7 days notice (QR_TOKEN_LIFETIME_DAYS default = 7).

**Step 2 — Rotate:**
Generate a new secret:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```
```env
QR_TOKEN_SECRET=<new value>
```
Deploy.

**Step 3 — Reprint QR codes.**
Complex admins must regenerate and redistribute QR codes from the admin panel.
Old QR codes are now invalid (`QRTokenService.validate()` will raise `QRTokenInvalidError`).

---

## 4. DATABASE_URL Password

**What it protects:** The PostgreSQL user password used by the Django application.  
**Risk if compromised:** Full database access (read + write, but limited by DB role permissions).  
**Recommended rotation period:** Every 90 days.  
**Zero-downtime:** ✅ Supported via PostgreSQL role password change + connection pool drain.

### Rotation steps

**Step 1 — Change password in PostgreSQL (does NOT disconnect existing connections):**
```sql
ALTER ROLE yali_app WITH PASSWORD '<new_password>';
```

**Step 2 — Update env and deploy:**
```env
DATABASE_URL=postgres://yali_app:<new_password>@<host>:<port>/<db>
```
On deploy, PgBouncer (or Django's connection pool) will establish new connections with the new password. Existing connections (in-flight requests) use the old auth — they will error on the next checkout from the pool.

**Step 3 — Drain the pool:**
```bash
# If using PgBouncer:
psql -U pgbouncer -c "RECONNECT yali_app;"
```
Or restart the application server (brief downtime) to force all connections to re-authenticate.

**Step 4 — Revoke the old password:**
This happened in Step 1 — `ALTER ROLE ... WITH PASSWORD` replaces the password immediately.

> [!NOTE]
> With `CONN_MAX_AGE=0` (our PgBouncer transaction mode setting), each request gets a fresh connection from PgBouncer's pool. PgBouncer holds the actual PostgreSQL connections. After Step 1, PgBouncer's existing server-side connections remain valid until they're closed and re-established.

---

## 5. TWILIO Credentials

**What it protects:** `TWILIO_AUTH_TOKEN` authenticates API calls to send OTP SMS messages.  
**Risk if compromised:** Attacker can send SMS from the Twilio account (Twilio billing fraud), enumerate phone numbers.  
**Recommended rotation period:** Every 90 days.  
**Zero-downtime:** ✅ Twilio supports dual auth tokens during rotation.

### Rotation steps

1. In the Twilio Console: **Account → API Keys** → Create a new Auth Token (secondary).
2. Update env:
   ```env
   TWILIO_AUTH_TOKEN=<new_auth_token>
   TWILIO_ACCOUNT_SID=<unchanged>
   ```
3. Deploy. Test an OTP send via `/auth/login/`.
4. In the Twilio Console: revoke the old Auth Token.

For `TWILIO_VERIFY_SERVICE_SID`: this is a service identifier, not a secret. It does not need rotation.

---

## 6. Cloudflare R2 Credentials

**What it protects:** `R2_ACCESS_KEY_ID` and `R2_SECRET_ACCESS_KEY` authenticate object storage operations.  
**Risk if compromised:** Attacker can read/write/delete media files in R2 bucket.  
**Recommended rotation period:** Every 90 days.  
**Zero-downtime:** ✅ Create new key before deleting old.

### Rotation steps

1. In Cloudflare Dashboard: **R2 → Manage R2 API Tokens** → Create new API token with same permissions.
2. Update env:
   ```env
   R2_ACCESS_KEY_ID=<new_key_id>
   R2_SECRET_ACCESS_KEY=<new_secret_key>
   ```
3. Deploy. Test a media upload (maintenance ticket photo, for example).
4. In Cloudflare Dashboard: delete the old API token.

---

## 7. Post-Rotation Verification Checklist

Run after **every** rotation:

```bash
# 1. JWT secret entropy check
python manage.py rotate_jwt_secret --verify

# 2. Full gate — zero failures required
make gate

# 3. Health check endpoint
curl -f https://api.yali.app/health/ | python -m json.tool

# 4. Auth smoke test (requires test account)
# POST /auth/login/ → receive OTP
# POST /auth/verify-otp/ → receive access + refresh token
# GET /auth/me/ → 200 OK with user data
# POST /auth/token/refresh/ → receive new token pair
# POST /auth/logout/ → 204 No Content
```

Watch Sentry for 15 minutes post-deploy. Alert thresholds:
- Auth 401 rate > 0.1% of requests → rollback immediately
- Auth 403 rate spike → check RLS policy state
- OTP send failure rate > 5% → check Twilio credentials

---

## 8. Emergency: Immediate Revocation

If a secret is confirmed compromised:

### JWT_SECRET_KEY compromised

**Immediate action (causes all users to be logged out — acceptable tradeoff):**
```env
JWT_SECRET_KEY=<new key>
JWT_PREVIOUS_SECRET_KEY=   # empty — do NOT set; revoke ALL old tokens
```
Deploy immediately. All active sessions are terminated. Users must log in again via OTP.

Then file a security incident report and notify affected users if required by your data protection obligations.

### DATABASE_URL compromised

```sql
-- Block all existing connections immediately
SELECT pg_terminate_backend(pg_stat_activity.pid)
FROM pg_stat_activity
WHERE pg_stat_activity.datname = '<db_name>'
  AND pid <> pg_backend_pid();

-- Change password
ALTER ROLE yali_app WITH PASSWORD '<emergency_new_password>';
```
Update `DATABASE_URL` env and deploy.

---

*Maintained by: Yali Engineering*  
*Related documents: ADR-010, ADR-011, ADR-012, auth_patterns_2026.md*
