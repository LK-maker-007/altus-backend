from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("visitors", "0001_initial"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="visitor",
            name="visitor_otp_unique_per_complex",
        ),
        migrations.AddConstraint(
            model_name="visitor",
            constraint=models.UniqueConstraint(
                fields=["complex", "otp_code"],
                condition=models.Q(status="pending"),
                name="visitor_otp_unique_per_complex_pending",
            ),
        ),
    ]
