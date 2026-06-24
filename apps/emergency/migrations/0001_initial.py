import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="EmergencyContact",
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
                ("role", models.CharField(max_length=200)),
                ("phone_number", models.CharField(max_length=20)),
                ("display_order", models.SmallIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "complex",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.RESTRICT, to="core.complex"
                    ),
                ),
            ],
            options={
                "ordering": ["display_order"],
                "indexes": [
                    models.Index(
                        fields=["complex", "is_active", "display_order"],
                        name="emergency_e_complex_1ba594_idx",
                    )
                ],
            },
        ),
    ]
