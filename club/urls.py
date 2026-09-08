from django.urls import path

from . import views

app_name = "club"

urlpatterns = [
    path("", views.home, name="home"),
    path("admin-pin/", views.admin_pin, name="admin_pin"),
    path("admin-pin/exit/", views.admin_exit, name="admin_exit"),
]
