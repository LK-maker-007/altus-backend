import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Announcement",
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
                ("title", models.CharField(max_length=300)),
                ("body", models.TextField()),
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("general", "General"),
                            ("maintenance", "Maintenance"),
                            ("event", "Event"),
                            ("power_outage", "Power Outage"),
                        ],
                        default="general",
                        max_length=20,
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
            ],
        ),
    ]
