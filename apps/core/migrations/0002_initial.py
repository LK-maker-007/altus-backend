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
        migrations.AddField(
            model_name="unit",
            name="registered_resident",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="unit",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddConstraint(
            model_name="subscription",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("status__in", ["active", "suspended", "cancelled"])
                ),
                name="subscription_status_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="subscription",
            constraint=models.CheckConstraint(
                condition=models.Q(("billing_cycle__in", ["monthly", "annual"])),
                name="subscription_billing_cycle_valid",
            ),
        ),
        migrations.AddIndex(
            model_name="unit",
            index=models.Index(
                fields=["complex", "building_block", "unit_number"],
                name="core_unit_complex_436706_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="unit",
            index=models.Index(
                fields=["registered_resident"], name="core_unit_registe_525e0b_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="unit",
            constraint=models.UniqueConstraint(
                fields=("complex", "unit_number", "building_block"),
                name="unit_number_unique_per_complex_block",
            ),
        ),
    ]
