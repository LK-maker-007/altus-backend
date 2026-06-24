import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("core", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Visitor",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("visitor_name", models.CharField(max_length=200)),
                (
                    "visitor_phone",
                    models.CharField(blank=True, default="", max_length=20),
                ),
                ("expected_from", models.DateTimeField()),
                ("expected_until", models.DateTimeField()),
                ("otp_code", models.CharField(max_length=6)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("arrived", "Arrived"),
                            ("expired", "Expired"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("arrived_at", models.DateTimeField(blank=True, null=True)),
                (
                    "complex",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.RESTRICT, to="core.complex"
                    ),
                ),
                (
                    "marked_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="verified_visitors",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "registered_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="registered_visitors",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "unit",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="visitors",
                        to="core.unit",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["complex", "otp_code", "status"],
                        name="visitors_vi_complex_72ebd7_idx",
                    ),
                    models.Index(
                        fields=["unit", "created_at"],
                        name="visitors_vi_unit_id_d66d86_idx",
                    ),
                    models.Index(
                        fields=["status", "expected_until"],
                        name="visitors_vi_status_b27932_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("complex", "otp_code"),
                        name="visitor_otp_unique_per_complex",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("expected_until__gt", models.F("expected_from"))
                        ),
                        name="visitor_window_valid",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("status__in", ["pending", "arrived", "expired"])
                        ),
                        name="visitor_status_valid",
                    ),
                ],
            },
        ),
    ]
