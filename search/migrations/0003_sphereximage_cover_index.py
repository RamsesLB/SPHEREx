from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("search", "0002_sphereximage"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="sphereximage",
            index=models.Index(fields=["collection", "dec_min", "dec_max"], name="spherex_cover_idx"),
        ),
    ]
