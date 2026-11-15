from django.db import migrations, models

CHOICES = [("leaflet", "Tract boîté"), ("mailbox_inaccessible", "Boîte aux lettres inaccessible")]


class Migration(migrations.Migration):

    dependencies = [
        ("canvassing", "0005_address_full_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="tourstop",
            name="absent_detail",
            field=models.CharField(blank=True, choices=CHOICES, default="", max_length=32),
        ),
        migrations.AddField(
            model_name="visit",
            name="absent_detail",
            field=models.CharField(blank=True, choices=CHOICES, default="", max_length=32),
        ),
    ]
