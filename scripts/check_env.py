from __future__ import annotations

#!/usr/bin/env python
"""
Pre-deployment environment variable check.

Crashes loudly with a descriptive error if any required env var is missing
or set to a known insecure default value.

Usage:
  python scripts/check_env.py

Exit codes:
  0 — all required vars present and not dangerous
  1 — one or more vars missing or dangerous

This script is called by the CI pipeline and should be run before
any production deployment. It is NOT part of the Django startup
because it is designed to be a human-readable gate, not an exception.
"""

import os
import sys

REQUIRED_VARS: list[str] = [
    "SECRET_KEY",
    "JWT_SECRET_KEY",
    "DATABASE_URL",
    "REDIS_URL",
    "QR_TOKEN_SECRET",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_VERIFY_SERVICE_SID",
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_ENDPOINT_URL",
    "R2_PUBLIC_URL",
    "ALLOWED_HOSTS",
    "SENTRY_DSN",
]

# Known insecure default values — reject these even if present
DANGEROUS_VALUES: set[str] = {
    "change-me",
    "secret",
    "password",
    "admin",
    "ci",
    "ACci",
    "VAci",
    "",
    "ci-test-secret-key-not-for-production-do-not-use",
    "ci-test-jwt-secret-not-for-production-do-not-use",
    "ci-test-qr-secret-not-for-production-do-not-use",
}


def main() -> int:
    errors: list[str] = []

    for var in REQUIRED_VARS:
        value = os.environ.get(var)
        if value is None:
            errors.append(f"MISSING: {var} is not set")
        elif value in DANGEROUS_VALUES:
            errors.append(f"INSECURE: {var} is set to a known dangerous default value")

    if errors:
        print(  # noqa: T201 - CLI script, print is intentional
            "Environment check FAILED - cannot deploy:\n", file=sys.stderr
        )
        for e in errors:
            print(f"  {e}", file=sys.stderr)  # noqa: T201
        print(  # noqa: T201 - CLI script, print is intentional
            "Fix all issues above before deploying to production.", file=sys.stderr
        )
        return 1

    print(  # noqa: T201 — CLI script, print is intentional
        f"Environment check passed - {len(REQUIRED_VARS)} vars verified."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
