import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Complex",
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
                ("name", models.CharField(max_length=200)),
                ("slug", models.SlugField(max_length=100, unique=True)),
                ("address", models.TextField()),
                ("city", models.CharField(max_length=100)),
                ("state", models.CharField(max_length=100)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "registration_token",
                    models.CharField(blank=True, max_length=512, null=True),
                ),
                (
                    "registration_token_expires_at",
                    models.DateTimeField(blank=True, null=True),
                ),
            ],
            options={
                "verbose_name_plural": "complexes",
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="Plan",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("name", models.CharField(max_length=100)),
                ("max_units", models.PositiveIntegerField()),
                ("price_monthly_inr", models.PositiveIntegerField()),
                ("price_annual_inr", models.PositiveIntegerField()),
                ("features", models.JSONField(default=dict)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name="Subscription",
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
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("active", "Active"),
                            ("suspended", "Suspended"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="active",
                        max_length=20,
                    ),
                ),
                (
                    "billing_cycle",
                    models.CharField(
                        choices=[("monthly", "Monthly"), ("annual", "Annual")],
                        max_length=10,
                    ),
                ),
                ("billing_start", models.DateField()),
                ("next_billing_date", models.DateField()),
                ("notes", models.TextField(blank=True, default="")),
                (
                    "complex",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.RESTRICT, to="core.complex"
                    ),
                ),
                (
                    "plan",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.RESTRICT, to="core.plan"
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="Unit",
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
                ("unit_number", models.CharField(max_length=20)),
                ("building_block", models.CharField(max_length=50)),
                ("floor", models.SmallIntegerField()),
                (
                    "complex",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.RESTRICT, to="core.complex"
                    ),
                ),
            ],
            options={
                "ordering": ["building_block", "floor", "unit_number"],
            },
        ),
    ]
