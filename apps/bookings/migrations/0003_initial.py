import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("bookings", "0002_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="booking",
            name="resident",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.RESTRICT,
                related_name="bookings",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddIndex(
            model_name="booking",
            index=models.Index(
                fields=["facility", "slot_start", "slot_end", "status"],
                name="bookings_bo_facilit_879695_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="booking",
            index=models.Index(
                fields=["resident", "status", "slot_start"],
                name="bookings_bo_residen_46f7d5_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="booking",
            index=models.Index(
                fields=["complex", "status", "created_at"],
                name="bookings_bo_complex_51416b_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="booking",
            index=models.Index(
                condition=models.Q(("status", "hold")),
                fields=["expires_at"],
                name="booking_hold_expiry_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="booking",
            constraint=models.CheckConstraint(
                condition=models.Q(("slot_end__gt", models.F("slot_start"))),
                name="booking_slot_end_after_start",
            ),
        ),
        migrations.AddConstraint(
            model_name="booking",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("status__in", ["hold", "confirmed", "cancelled", "expired"])
                ),
                name="booking_status_valid",
            ),
        ),
    ]
