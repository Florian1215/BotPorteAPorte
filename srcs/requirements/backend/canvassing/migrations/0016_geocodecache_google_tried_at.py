from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("canvassing", "0015_retry_not_geocoded")]
    operations = [
        migrations.AddField(
            model_name="geocodecache", name="google_tried_at", field=models.DateTimeField(blank=True, null=True)
        ),
    ]
