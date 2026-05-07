from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_alter_customerprofile_customer_type_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="producerprofile",
            name="lead_time_days",
            field=models.PositiveSmallIntegerField(default=2),
        ),
    ]
