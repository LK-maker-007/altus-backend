import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("bookings", "0001_initial"),
        ("core", "0001_initial"),
        ("facilities", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="booking",
            name="complex",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.RESTRICT, to="core.complex"
            ),
        ),
        migrations.AddField(
            model_name="booking",
            name="facility",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.RESTRICT,
                related_name="bookings",
                to="facilities.facility",
            ),
        ),
    ]
