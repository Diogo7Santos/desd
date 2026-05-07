from django.db import migrations


def normalize_legacy_seasonal_category(apps, schema_editor):
    Product = apps.get_model("catalog", "Product")
    Product.objects.filter(category="SEASONAL_SPECIALTIES").update(category="SEASONAL")


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0002_product_organic_status_and_more"),
    ]

    operations = [
        migrations.RunPython(
            normalize_legacy_seasonal_category,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
