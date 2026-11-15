from django.contrib import admin

from .models import AllwiseAnchor, ExampleSkyObject, ImageTest, SpherexCollection, SpherexImage


@admin.register(ImageTest)
class ImageTestAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "img")
    search_fields = ("name",)


@admin.register(ExampleSkyObject)
class ExampleSkyObjectAdmin(admin.ModelAdmin):
    list_display = ("name", "ra", "dec", "fov", "unit", "sort_order", "is_active")
    list_editable = ("sort_order", "is_active")
    search_fields = ("name", "description", "ra", "dec")
    list_filter = ("unit", "is_active")


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


@admin.register(AllwiseAnchor)
class AllwiseAnchorAdmin(admin.ModelAdmin):
    list_display = ("ra", "dec", "year", "w1mpro", "updated_at")
    search_fields = ("ra", "dec")
    readonly_fields = ("updated_at",)
