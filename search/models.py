from django.db import models

# Create your models here.
class ImageTest(models.Model):
    '''
    Model created to test Cloudflare R2 correct functionality
    '''
    name = models.CharField(max_length=80)
    img = models.ImageField(upload_to='testing/', null=True, blank=True)