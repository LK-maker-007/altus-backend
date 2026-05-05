"""
Migration: fix visitor OTP unique constraint to be partial (status=PENDING only).

WHY this migration is needed:
  The previous constraint `visitor_otp_unique_per_complex` had no condition — it
  applied to ALL visitor records regardless of status. Over time, ARRIVED and EXPIRED
  records permanently consumed their 6-digit OTP codes (000000-999999 space).

  A complex with 100 visitors/day would exhaust the 1,000,000-code space after ~27 years.
  More critically, the application-layer `_generate_unique_otp()` already filters
  status=PENDING — so the DB constraint was stricter than the application logic,
  creating a mismatch that could cause silent IntegrityError under load.

  The fix: DROP the old unconditional constraint, CREATE a partial constraint that
  matches the application-layer logic exactly.

  Source: Google Principal Architect review §SIGNIFICANT "visitor_otp_unique_per_complex
          Constraint Is Wrong"
"""

from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("visitors", "0001_initial"),
    ]

    operations = [
        # Step 1: Remove the unconditional constraint that covers ALL statuses.
        migrations.RemoveConstraint(
            model_name="visitor",
            name="visitor_otp_unique_per_complex",
        ),
        # Step 2: Add the correct partial constraint — only PENDING visitors
        # must have unique OTP codes within a complex. ARRIVED and EXPIRED records
        # are free to share codes, preventing code space exhaustion.
        migrations.AddConstraint(
            model_name="visitor",
            constraint=models.UniqueConstraint(
                fields=["complex", "otp_code"],
                condition=models.Q(status="pending"),
                name="visitor_otp_unique_per_complex_pending",
            ),
        ),
    ]
