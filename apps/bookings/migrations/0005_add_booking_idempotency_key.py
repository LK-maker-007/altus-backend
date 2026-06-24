from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bookings", "0004_gist_exclusion_constraint_no_overlap"),
        ("core", "0003_rls_policies"),
        ("facilities", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="booking",
            name="client_idempotency_key",
            field=models.UUIDField(blank=True, editable=False, null=True),
        ),
        migrations.AddConstraint(
            model_name="booking",
            constraint=models.UniqueConstraint(
                condition=models.Q(("client_idempotency_key__isnull", False)),
                fields=("client_idempotency_key",),
                name="booking_idempotency_key_unique",
            ),
        ),
    ]
