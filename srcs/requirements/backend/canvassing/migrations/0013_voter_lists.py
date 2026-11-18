"""Addresses move from the organization to a voter list (LEC) that several organizations can share.

Each organization that had addresses gets its own list (named after its city), so nothing changes for it.
"""
from django.db import migrations, models
import django.db.models.deletion


def create_lists(apps, schema_editor):
    Organization = apps.get_model("accounts", "Organization")
    VoterList = apps.get_model("accounts", "VoterList")
    Address = apps.get_model("canvassing", "Address")
    AddressImport = apps.get_model("canvassing", "AddressImport")
    for organization in Organization.objects.all():
        has_addresses = Address.objects.filter(organization=organization).exists()
        has_imports = AddressImport.objects.filter(organization=organization).exists()
        if not (has_addresses or has_imports):
            continue
        voter_list = VoterList.objects.create(
            name=f"LEC {organization.city or organization.name}", country_code=organization.country_code
        )
        organization.voter_list = voter_list
        organization.save(update_fields=["voter_list"])
        Address.objects.filter(organization=organization).update(voter_list=voter_list)
        AddressImport.objects.filter(organization=organization).update(voter_list=voter_list)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0010_voter_lists"),
        ("canvassing", "0012_telegram_link"),
    ]

    operations = [
        migrations.AddField(
            model_name="address",
            name="voter_list",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="addresses",
                to="accounts.voterlist",
                verbose_name="LEC",
            ),
        ),
        migrations.AddField(
            model_name="addressimport",
            name="voter_list",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.CASCADE, related_name="imports", to="accounts.voterlist"
            ),
        ),
        migrations.RunPython(create_lists, migrations.RunPython.noop),
    ]
