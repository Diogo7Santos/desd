from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0005_recurringorder_recurringorderitem_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="orderitem",
            name="producer_delivery_date",
            field=models.DateField(
                blank=True,
                help_text="Requested delivery date for this producer's items.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="orderitem",
            name="producer_delivery_notes",
            field=models.TextField(
                blank=True,
                help_text="Delivery notes specific to this producer's items.",
            ),
        ),
    ]
