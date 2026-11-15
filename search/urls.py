from django.urls import path
from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("refresh/", views.refresh, name="refresh"),
    path("cutout/sum/", views.sum_cutout, name="sum_cutout"),
    path("cutout/<int:pk>/", views.cutout, name="cutout"),
    path("health/", views.health_check, name="health_check"),
]
