from django.db import models


class ImageTest(models.Model):
    '''
    Model created to test Cloudflare R2 correct functionality
    '''
    name = models.CharField(max_length=80)
    img = models.ImageField(upload_to='testing/', null=True, blank=True)


class SpherexImage(models.Model):
    obs_id = models.CharField(max_length=255)
    access_url = models.URLField(max_length=1000, unique=True)

    ra_center = models.FloatField()
    dec_center = models.FloatField()

    # Reservado para acotar búsquedas sin PostGIS. Esta versión no lo rellena.
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

    def __str__(self):
        detector = f" D{self.detector}" if self.detector else ""
        return f"{self.obs_id}{detector} - {self.observation_date}"
