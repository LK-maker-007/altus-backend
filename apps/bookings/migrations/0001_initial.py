import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Booking",
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
                ("slot_start", models.DateTimeField()),
                ("slot_end", models.DateTimeField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("hold", "Hold"),
                            ("confirmed", "Confirmed"),
                            ("cancelled", "Cancelled"),
                            ("expired", "Expired"),
                        ],
                        default="hold",
                        max_length=20,
                    ),
                ),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("cancelled_at", models.DateTimeField(blank=True, null=True)),
                ("cancellation_reason", models.TextField(blank=True, default="")),
                (
                    "cancellation_source",
                    models.CharField(
                        blank=True,
                        choices=[("resident", "Resident"), ("admin", "Admin")],
                        default="",
                        max_length=20,
                    ),
                ),
            ],
        ),
    ]
