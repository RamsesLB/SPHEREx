from django.db import migrations, models


SEED_OBJECTS = (
    {
        "name": "RW Aurigae A",
        "description": (
            "Young T Tauri star in Auriga with an accretion disk and jets. "
            "Coordinates match SIMBAD/Gaia J2000."
        ),
        "ra": "05h07m49.4562s",
        "dec": "+30d24m04.774s",
        "fov": 200,
        "unit": "arcsec",
        "sort_order": 10,
    },
    {
        "name": "Barnard's Star",
        "description": (
            "Nearest red dwarf with the largest known proper motion (~10.3″/yr nearly north). "
            "Position is approximate epoch 2025 so SPHEREx frames land near the star; "
            "J2000 is about 17h57m48.50s +04d41m36.1s."
        ),
        "ra": "17h57m47.16s",
        "dec": "+04d45m55.2s",
        "fov": 300,
        "unit": "arcsec",
        "sort_order": 20,
    },
    {
        "name": "Epsilon Indi B",
        "description": (
            "Nearest binary brown dwarf (ε Ind Ba/Bb), ~12 ly away. "
            "SIMBAD J2000 for Ba; the coords 22h03m21.65s −56d47m09.5s belong to ε Ind A, ~7′ away."
        ),
        "ra": "22h04m10.595s",
        "dec": "-56d46m58.239s",
        "fov": 200,
        "unit": "arcsec",
        "sort_order": 30,
    },
    {
        "name": "WISE 0855",
        "description": (
            "Cold Y dwarf WISE J085510.83−071442.5, one of the Sun’s nearest neighbors. "
            "Uses the discovery position encoded in the name; it has large proper motion (~8″/yr)."
        ),
        "ra": "08h55m10.831s",
        "dec": "-7d14m42.53s",
        "fov": 300,
        "unit": "arcsec",
        "sort_order": 40,
    },
)


def seed_examples(apps, schema_editor):
    ExampleSkyObject = apps.get_model("search", "ExampleSkyObject")
    if ExampleSkyObject.objects.exists():
        return
    ExampleSkyObject.objects.bulk_create(
        [ExampleSkyObject(**row) for row in SEED_OBJECTS]
    )


class Migration(migrations.Migration):

    dependencies = [
        ("search", "0005_spherexcollection"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExampleSkyObject",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=80)),
                ("description", models.TextField(blank=True, default="")),
                ("ra", models.CharField(max_length=50)),
                ("dec", models.CharField(max_length=50)),
                ("fov", models.FloatField(default=60)),
                (
                    "unit",
                    models.CharField(
                        choices=[
                            ("arcsec", "Arcseconds"),
                            ("arcmin", "Arcminutes"),
                            ("deg", "Degrees"),
                        ],
                        default="arcsec",
                        max_length=6,
                    ),
                ),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={
                "ordering": ["sort_order", "name"],
            },
        ),
        migrations.RunPython(seed_examples, migrations.RunPython.noop),
    ]
