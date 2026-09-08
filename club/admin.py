from django.contrib import admin

from .models import Book, Member


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    """The roster's only editing surface until #5 builds one in the app.

    No ``ordering`` here on purpose: setting it would override
    ``Member.Meta.ordering`` and bring back the case-sensitive sort.
    """

    list_display = ("name", "role", "is_active", "joined_on")
    list_filter = ("is_active",)
    search_fields = ("name",)

    def has_delete_permission(self, request, obj=None):
        """Members are deactivated, never deleted — decision #3."""
        return False

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    """Books can be added here until #14 builds the start and finish flows.

    No ``ordering`` here on purpose: it would override ``Book.Meta.ordering``
    and lose the explicit null placement on the two nullable dates.
    """

    list_display = (
        "title",
        "author",
        "is_current",
        "started_on",
        "finished_on",
        "rating",
        "total_pages",
    )
    list_filter = ("is_current",)
    search_fields = ("title", "author")
