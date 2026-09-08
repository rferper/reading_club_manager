from django.urls import path

from . import views

app_name = "club"

urlpatterns = [
    path("", views.home, name="home"),
    path("admin-pin/", views.admin_pin, name="admin_pin"),
    path("admin-pin/exit/", views.admin_exit, name="admin_exit"),
    path("who-are-you/", views.identify, name="identify"),
    path("who-are-you/forget/", views.forget_me, name="forget_me"),
    path("members/", views.member_list, name="member_list"),
    path("members/add/", views.member_add, name="member_add"),
    path("members/<int:pk>/edit/", views.member_edit, name="member_edit"),
    path("members/<int:pk>/toggle/", views.member_toggle, name="member_toggle"),
]
