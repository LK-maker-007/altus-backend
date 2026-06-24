import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("community", "0001_initial"),
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="announcement",
            name="complex",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.RESTRICT, to="core.complex"
            ),
        ),
    ]
