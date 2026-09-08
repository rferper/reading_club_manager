from django.urls import path

from . import views

app_name = "club"

urlpatterns = [
    path("", views.home, name="home"),
]
