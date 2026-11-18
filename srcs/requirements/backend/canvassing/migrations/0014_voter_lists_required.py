from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("canvassing", "0013_voter_lists"),
    ]

    operations = [
        migrations.RemoveIndex(model_name="address", name="canvassing__organiz_status_idx"),
        migrations.RemoveIndex(model_name="address", name="canvassing__organiz_srckey_idx"),
        migrations.RemoveField(model_name="address", name="organization"),
        migrations.RemoveField(model_name="addressimport", name="organization"),
        migrations.AlterField(
            model_name="address",
            name="voter_list",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="addresses",
                to="accounts.voterlist",
                verbose_name="LEC",
            ),
        ),
        migrations.AlterField(
            model_name="addressimport",
            name="voter_list",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE, related_name="imports", to="accounts.voterlist"
            ),
        ),
        migrations.AddIndex(
            model_name="address",
            index=models.Index(fields=["voter_list", "status"], name="canvassing_address_list_status"),
        ),
        migrations.AddIndex(
            model_name="address",
            index=models.Index(fields=["voter_list", "source_key"], name="canvassing_address_list_key"),
        ),
    ]
