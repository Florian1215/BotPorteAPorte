from django.db import migrations


def forget_not_found(apps, schema_editor):
    # Addresses that were not found are looked up again by the next import, now typo-tolerant.
    apps.get_model("canvassing", "GeocodeCache").objects.filter(found=False).delete()


class Migration(migrations.Migration):
    dependencies = [("canvassing", "0009_elections")]
    operations = [migrations.RunPython(forget_not_found, migrations.RunPython.noop)]
