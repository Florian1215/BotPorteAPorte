"""Addresses whose last visit (any election) was "ne plus déranger" or "adresse introuvable" go back to that
status: some were made available again by old imports or merges."""
from django.db import migrations
from django.db.models import OuterRef, Subquery

# VisitResult → Status (values frozen here, as in the models at the time of this migration).
KEPT = {"do_not_contact": 6, "address_failure": 2}
PLANNED = 1


def forwards(apps, schema_editor):
    Address = apps.get_model("canvassing", "Address")
    Visit = apps.get_model("canvassing", "Visit")
    last = Visit.objects.filter(address=OuterRef("pk")).order_by("-created_at", "-id").values("result")[:1]
    for result, status in KEPT.items():
        ids = (
            Address.objects.exclude(status__in=[status, PLANNED])
            .annotate(last_result=Subquery(last))
            .filter(last_result=result)
            .values("pk")
        )
        Address.objects.filter(pk__in=ids).update(status=status, visit_planned_by=None)


class Migration(migrations.Migration):
    dependencies = [
        ("canvassing", "0021_remove_ai_district_import"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
