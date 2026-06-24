from __future__ import annotations

from django.apps.registry import Apps
from django.conf import settings
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.utils import timezone


def backfill_event_dates(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    Announcement = apps.get_model("community", "Announcement")
    Announcement.objects.filter(category="event", event_date__isnull=True).update(
        event_date=timezone.now()
    )


def noop(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("community", "0003_initial"),
        ("core", "0003_rls_policies"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="announcement",
            name="event_date",
            field=models.DateTimeField(
                blank=True,
                help_text="Event start date/time (ISO 8601). Required when category=event.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="announcement",
            name="event_venue",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Venue / location of the event. Optional even for events.",
                max_length=200,
            ),
        ),
        migrations.RunPython(backfill_event_dates, reverse_code=noop),
        migrations.AddConstraint(
            model_name="announcement",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("category", "event"), _negated=True),
                    ("event_date__isnull", False),
                    _connector="OR",
                ),
                name="announcement_event_date_required_for_event",
            ),
        ),
    ]
