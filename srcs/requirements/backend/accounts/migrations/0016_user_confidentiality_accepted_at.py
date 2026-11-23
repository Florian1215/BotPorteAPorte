from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0015_organization_social_upload"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="confidentiality_accepted_at",
            field=models.DateTimeField(
                blank=True, editable=False, null=True, verbose_name="engagement de confidentialité accepté le"
            ),
        ),
    ]
