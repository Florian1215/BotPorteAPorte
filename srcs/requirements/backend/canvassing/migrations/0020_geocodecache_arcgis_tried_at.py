"""Geocoding fallback: Google → ArcGIS. A new "tried" date, so that the addresses Google could not locate are
sent once to ArcGIS at the next import."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("canvassing", "0019_visit_not_interested"),
    ]

    operations = [
        migrations.RemoveField(model_name="geocodecache", name="google_tried_at"),
        migrations.AddField(
            model_name="geocodecache", name="arcgis_tried_at", field=models.DateTimeField(blank=True, null=True)
        ),
    ]
