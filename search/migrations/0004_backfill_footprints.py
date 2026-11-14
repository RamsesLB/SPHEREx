from django.db import migrations

FOOTPRINT_HALF_DEG = 2.0


def fill_missing_boxes(apps, schema_editor):
    SpherexImage = apps.get_model("search", "SpherexImage")
    pending = SpherexImage.objects.filter(ra_min__isnull=True)
    for image in pending.iterator():
        ra = float(image.ra_center) % 360.0
        dec = float(image.dec_center)
        image.ra_min = (ra - FOOTPRINT_HALF_DEG) % 360.0
        image.ra_max = (ra + FOOTPRINT_HALF_DEG) % 360.0
        image.dec_min = max(-90.0, dec - FOOTPRINT_HALF_DEG)
        image.dec_max = min(90.0, dec + FOOTPRINT_HALF_DEG)
        image.save(update_fields=["ra_min", "ra_max", "dec_min", "dec_max"])


class Migration(migrations.Migration):

    dependencies = [
        ("search", "0003_sphereximage_cover_index"),
    ]

    operations = [
        migrations.RunPython(fill_missing_boxes, migrations.RunPython.noop),
    ]
