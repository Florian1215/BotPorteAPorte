"""The AI import of the zones is removed: its agent configuration and the fields of its imports."""
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("canvassing", "0020_geocodecache_arcgis_tried_at"),
    ]

    operations = [
        migrations.RemoveField(model_name="districtimport", name="hint"),
        migrations.RemoveField(model_name="districtimport", name="ai_session_id"),
        migrations.RemoveField(model_name="districtimport", name="progress_log"),
        migrations.DeleteModel(name="AiAgentConfig"),
    ]
