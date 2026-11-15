from django.urls import path
from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("information/", views.information, name="information"),
    path("refresh/", views.refresh, name="refresh"),
    path("catalog/allwise/", views.allwise_catalog, name="allwise_catalog"),
    path("cutout/sum/", views.sum_cutout, name="sum_cutout"),
    path("cutout/diff/", views.diff_cutout, name="diff_cutout"),
    path("cutout/<int:pk>/", views.cutout, name="cutout"),
    path("health/", views.health_check, name="health_check"),
]
