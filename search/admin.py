from django.contrib import admin

from .models import ImageTest, SpherexCollection, SpherexImage


@admin.register(ImageTest)
class ImageTestAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "img")
    search_fields = ("name",)


@admin.register(SpherexCollection)
class SpherexCollectionAdmin(admin.ModelAdmin):
    list_display = ("name", "updated_at")
    search_fields = ("name",)
    readonly_fields = ("updated_at",)


@admin.register(SpherexImage)
class SpherexImageAdmin(admin.ModelAdmin):
    list_display = ("obs_id", "detector", "observation_date", "collection", "ra_center", "dec_center")
    search_fields = ("obs_id", "access_url", "collection")
    list_filter = ("detector", "collection")
