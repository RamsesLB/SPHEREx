from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("search", "0006_exampleskyobject"),
    ]

    operations = [
        migrations.CreateModel(
            name="AllwiseAnchor",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ra", models.FloatField()),
                ("dec", models.FloatField()),
                ("year", models.PositiveSmallIntegerField(default=2010)),
                ("w1mpro", models.FloatField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("ra", "dec"), name="allwise_anchor_pos"),
                ],
            },
        ),
    ]
