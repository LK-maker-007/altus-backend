from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("maintenance", "0002_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="ticketstatushistory",
            name="status",
            field=models.CharField(
                choices=[
                    ("open", "Open"),
                    ("in_progress", "In Progress"),
                    ("resolved", "Resolved"),
                    ("closed", "Closed"),
                ],
                max_length=20,
            ),
        ),
        migrations.AddConstraint(
            model_name="ticketstatushistory",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("status__in", ["open", "in_progress", "resolved", "closed"])
                ),
                name="ticket_status_history_status_valid",
            ),
        ),
    ]
