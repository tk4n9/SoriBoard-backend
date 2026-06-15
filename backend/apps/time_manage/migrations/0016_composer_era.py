from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("time_manage", "0015_timeinfo_m2m"),
    ]

    operations = [
        migrations.AddField(
            model_name="composer",
            name="birth_year",
            field=models.IntegerField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name="composer",
            name="era_override",
            field=models.CharField(blank=True, default=None, max_length=20, null=True),
        ),
    ]
