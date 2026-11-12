from django.contrib import admin
from .models import ImageTest

# Register your models here.
@admin.register(ImageTest)
class ImageTestAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'img')
    search_fields = ('name',)