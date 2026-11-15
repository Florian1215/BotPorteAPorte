import hashlib

from django.db import migrations


def backfill(apps, schema_editor):
    """Same formula as canvassing.models.address_key (copied: migrations must not import live code)."""
    Address = apps.get_model("canvassing", "Address")
    batch = []
    for a in Address._base_manager.filter(source_key="").only("name", "first_names", "address", "zip_code", "city").iterator(chunk_size=2000):
        parts = [" ".join(str(p).lower().split()) for p in (a.name, a.first_names, a.address, a.zip_code, a.city)]
        a.source_key = "k:" + hashlib.sha256("|".join(parts).encode()).hexdigest()[:40]
        batch.append(a)
        if len(batch) >= 2000:
            Address._base_manager.bulk_update(batch, ["source_key"])
            batch.clear()
    Address._base_manager.bulk_update(batch, ["source_key"])


class Migration(migrations.Migration):

    dependencies = [
        ("canvassing", "0003_address_import_key_and_disabled"),
    ]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
