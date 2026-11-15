import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_organizations_and_roles"),
        ("canvassing", "0001_initial"),
    ]

    operations = [
        migrations.RemoveIndex(model_name="address", name="canvassing__scope_i_c69294_idx"),
        migrations.RenameField(model_name="address", old_name="scope", new_name="organization"),
        migrations.RenameField(model_name="area", old_name="scope", new_name="organization"),
        migrations.RenameField(model_name="tour", old_name="scope", new_name="organization"),
        migrations.AlterField(
            model_name="address",
            name="organization",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE, related_name="addresses", to="accounts.organization"
            ),
        ),
        migrations.AlterField(
            model_name="area",
            name="organization",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE, related_name="areas", to="accounts.organization"
            ),
        ),
        migrations.AlterField(
            model_name="tour",
            name="organization",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE, related_name="tours", to="accounts.organization"
            ),
        ),
        migrations.AddIndex(
            model_name="address",
            index=models.Index(fields=["organization", "status"], name="canvassing__organiz_status_idx"),
        ),
    ]
