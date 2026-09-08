"""URL configuration for the reading_club project.

The club's own routes live in `club/urls.py` under the `club` namespace and are
mounted at the site root. See `_docs/api.md` for the full URL surface.
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("club.urls")),
]
