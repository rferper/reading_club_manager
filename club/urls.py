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
    path("progress/", views.progress_overview, name="progress"),
    path("progress/update/", views.progress_update, name="progress_update"),
    path("notes/", views.notes, name="notes"),
    path("notes/<int:pk>/delete/", views.note_delete, name="note_delete"),
    path("questions/", views.questions, name="questions"),
    path("questions/add/", views.question_add, name="question_add"),
    path("questions/<int:pk>/edit/", views.question_edit, name="question_edit"),
    path(
        "questions/<int:pk>/delete/", views.question_delete, name="question_delete"
    ),
    path("history/", views.history, name="history"),
    path("history/<int:pk>/", views.history_detail, name="history_detail"),
    path("books/start/", views.book_start, name="book_start"),
    path("books/<int:pk>/edit/", views.book_edit, name="book_edit"),
    path("books/<int:pk>/finish/", views.book_finish, name="book_finish"),
    path("books/<int:pk>/rate/", views.book_rate, name="book_rate"),
]
