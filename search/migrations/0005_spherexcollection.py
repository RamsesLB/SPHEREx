from django.db import migrations, models

SEED_COLLECTIONS = (
    "spherex_qr3",
    "spherex_qr3_deep",
    "spherex_qr2",
    "spherex_qr2_deep",
    "spherex_dr1",
    "spherex_dr1_cube",
    "spherex_dr1_deep",
)


def seed_collections(apps, schema_editor):
    SpherexCollection = apps.get_model("search", "SpherexCollection")
    if SpherexCollection.objects.exists():
        return
    SpherexCollection.objects.bulk_create(
        [SpherexCollection(name=name) for name in SEED_COLLECTIONS]
    )


class Migration(migrations.Migration):

    dependencies = [
        ("search", "0004_backfill_footprints"),
    ]

    operations = [
        migrations.CreateModel(
            name="SpherexCollection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=64, unique=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["name"],
            },
        ),
        migrations.RunPython(seed_collections, migrations.RunPython.noop),
    ]
