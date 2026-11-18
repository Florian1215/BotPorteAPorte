from django.db import migrations


def forget_not_found(apps, schema_editor):
    # Addresses that were not found are looked up again by the next import: flat numbers ("4 Top 7"),
    # villages without streets ("Harbach 86"), glued names ("Schönhauserallee"), "c/o …" are now understood.
    apps.get_model("canvassing", "GeocodeCache").objects.filter(found=False).delete()


class Migration(migrations.Migration):
    dependencies = [("canvassing", "0014_voter_lists_required")]
    operations = [migrations.RunPython(forget_not_found, migrations.RunPython.noop)]
