from django.db import models


class ImageTest(models.Model):
    '''
    Model created to test Cloudflare R2 correct functionality
    '''
    name = models.CharField(max_length=80)
    img = models.ImageField(upload_to='testing/', null=True, blank=True)


class SpherexCollection(models.Model):
    name = models.CharField(max_length=64, unique=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ExampleSkyObject(models.Model):
    name = models.CharField(max_length=80)
    description = models.TextField(blank=True, default="")
    ra = models.CharField(max_length=50)
    dec = models.CharField(max_length=50)
    fov = models.FloatField(default=60)
    unit = models.CharField(
        max_length=6,
        choices=(
            ("arcsec", "Arcseconds"),
            ("arcmin", "Arcminutes"),
            ("deg", "Degrees"),
        ),
        default="arcsec",
    )
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class SpherexImage(models.Model):
    obs_id = models.CharField(max_length=255)
    access_url = models.URLField(max_length=1000, unique=True)

    ra_center = models.FloatField()
    dec_center = models.FloatField()

    # Bounding box of the frame. ra_min > ra_max means the box crosses 0°/360°.
    ra_min = models.FloatField(null=True, blank=True)
    ra_max = models.FloatField(null=True, blank=True)
    dec_min = models.FloatField(null=True, blank=True)
    dec_max = models.FloatField(null=True, blank=True)

    observation_date = models.DateTimeField()
    band = models.CharField(max_length=80, blank=True, default="")
    detector = models.PositiveSmallIntegerField(null=True, blank=True)
    em_min = models.FloatField(null=True, blank=True)
    em_max = models.FloatField(null=True, blank=True)
    collection = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        ordering = ["observation_date", "obs_id"]
        indexes = [
            models.Index(fields=["collection", "dec_min", "dec_max"], name="spherex_cover_idx"),
        ]

    def __str__(self):
        detector = f" D{self.detector}" if self.detector else ""
        return f"{self.obs_id}{detector} - {self.observation_date}"


class AllwiseAnchor(models.Model):
    """AllWISE catalog position saved after a successful IRSA query."""

    ra = models.FloatField()
    dec = models.FloatField()
    year = models.PositiveSmallIntegerField(default=2010)
    w1mpro = models.FloatField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["ra", "dec"], name="allwise_anchor_pos"),
        ]

    def __str__(self):
        return f"AllWISE {self.year} {self.ra:.5f} {self.dec:.5f}"
