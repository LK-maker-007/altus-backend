"""
apps/core/management/commands/rotate_jwt_secret.py

Zero-downtime JWT secret rotation assistant.

Usage:
    python manage.py rotate_jwt_secret          # Generate new key + print instructions
    python manage.py rotate_jwt_secret --verify  # Verify current secret meets minimum entropy

WHY a management command (not a script):
  Runs inside Django's settings context, so it can:
  - Read the current JWT_SECRET_KEY value directly from settings
  - Check minimum entropy against the configured value
  - Be run on the production server via `manage.py` without importing
    settings separately.

WHY it does NOT modify .env automatically:
  Automated secret rotation that modifies environment files is a security
  anti-pattern — it assumes write access to the .env file, bypasses
  review/audit, and could introduce race conditions in multi-server deploys.
  The operator must execute the steps with full understanding and audit trail.
"""

from __future__ import annotations

import argparse
import secrets

from django.conf import settings
from django.core.management.base import BaseCommand

_MIN_KEY_BYTES = 32  # 256-bit minimum for HS256 per RFC 7518 §3.2


class Command(BaseCommand):
    help = (
        "JWT secret rotation assistant. Generates a new cryptographically secure "
        "key and prints zero-downtime rotation instructions. Does NOT modify any "
        "files — operator action required."
    )

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--verify",
            action="store_true",
            help="Only verify that the current JWT_SECRET_KEY meets minimum entropy. "
            "Exits 0 if valid, 1 if not.",
        )

    def handle(self, *args: object, **options: object) -> None:
        verify_only = bool(options.get("verify"))

        current_key: str = settings.JWT_SECRET_KEY
        previous_key: str = settings.JWT_PREVIOUS_SECRET_KEY

        # ── Verify current key entropy ─────────────────────────────────────────
        current_key_bytes = len(current_key.encode())
        current_ok = current_key_bytes >= _MIN_KEY_BYTES

        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO("JWT Secret Rotation Assistant"))
        self.stdout.write("=" * 60)
        self.stdout.write("")

        status = (
            self.style.SUCCESS("✓ PASS") if current_ok else self.style.ERROR("✗ FAIL")
        )
        self.stdout.write(
            f"Current JWT_SECRET_KEY:  {current_key_bytes} bytes  {status}"
        )
        if not current_ok:
            self.stdout.write(
                self.style.ERROR(
                    f"  MINIMUM: {_MIN_KEY_BYTES} bytes ({_MIN_KEY_BYTES * 8} bits) "
                    f"per RFC 7518 §3.2 (HS256 minimum)."
                )
            )

        if previous_key:
            prev_bytes = len(previous_key.encode())
            prev_ok = prev_bytes >= _MIN_KEY_BYTES
            prev_status = (
                self.style.SUCCESS("✓ PASS") if prev_ok else self.style.ERROR("✗ FAIL")
            )
            self.stdout.write(
                f"JWT_PREVIOUS_SECRET_KEY: {prev_bytes} bytes  {prev_status}"
                "  (overlap window active — old tokens still accepted)"
            )
        else:
            self.stdout.write(
                "JWT_PREVIOUS_SECRET_KEY: not set  "
                "(no rotation in progress — single-key mode)"
            )

        if verify_only:
            self.stdout.write("")
            if current_ok:
                self.stdout.write(self.style.SUCCESS("Verification passed."))
            else:
                self.stderr.write(
                    self.style.ERROR("Verification FAILED. Rotate immediately.")
                )
                raise SystemExit(1)
            return

        # ── Generate new key ───────────────────────────────────────────────────
        # secrets.token_urlsafe(32):
        #   - 32 bytes = 256 bits of cryptographically secure random data
        #   - URL-safe base64 encoding: no characters that break .env files
        #   - Backed by os.urandom() — cryptographically secure PRNG
        #   Result: 43-character string with 256-bit entropy
        new_key = secrets.token_urlsafe(32)

        self.stdout.write("")
        self.stdout.write(self.style.WARNING("New key (generated — copy this value):"))
        self.stdout.write(f"  {new_key}")
        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO("Zero-downtime rotation steps:"))
        self.stdout.write("")
        self.stdout.write(
            "  Step 1:  Set JWT_PREVIOUS_SECRET_KEY = <current JWT_SECRET_KEY value>"
        )
        self.stdout.write(
            "           ↳ This preserves existing sessions during the overlap window."
        )
        self.stdout.write(
            "  Step 2:  Deploy. Both keys now accepted for token verification."
        )
        self.stdout.write("  Step 3:  Set JWT_SECRET_KEY = <new key printed above>")
        self.stdout.write("           ↳ New tokens are signed with the new key.")
        self.stdout.write(
            "           ↳ Old tokens (signed with previous key) still accepted."
        )
        self.stdout.write(
            "  Step 4:  Deploy. Monitor auth error rate in Sentry for 5 minutes."
        )
        self.stdout.write(
            f"  Step 5:  After {settings.JWT_REFRESH_TOKEN_LIFETIME_DAYS} days "
            f"(refresh token lifetime), ALL old tokens have naturally expired."
        )
        self.stdout.write("  Step 6:  Unset JWT_PREVIOUS_SECRET_KEY. Deploy.")
        self.stdout.write(
            "  Step 7:  Run `python manage.py rotate_jwt_secret --verify` to confirm."
        )
        self.stdout.write("")
        self.stdout.write(
            self.style.ERROR(
                "  WARNING: Do NOT skip Step 1. Setting a new JWT_SECRET_KEY without"
            )
        )
        self.stdout.write(
            self.style.ERROR(
                "           first setting JWT_PREVIOUS_SECRET_KEY will immediately"
            )
        )
        self.stdout.write(
            self.style.ERROR(
                "           invalidate ALL active sessions. Every user is logged out."
            )
        )
        self.stdout.write("")
        self.stdout.write("  Full runbook: docs/runbooks/secrets-rotation.md")
        self.stdout.write("")
