from django.contrib import admin

from .models import ImageTest, SpherexImage


@admin.register(ImageTest)
class ImageTestAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'img')
    search_fields = ('name',)


@admin.register(SpherexImage)
class SpherexImageAdmin(admin.ModelAdmin):
    list_display = ("obs_id", "detector", "observation_date", "collection", "ra_center", "dec_center")
    search_fields = ("obs_id", "access_url", "collection")
    list_filter = ("detector", "collection")
