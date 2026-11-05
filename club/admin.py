from django import forms
from django.contrib import admin

from .duration import MinutesField, format_minutes
from .models import Book, Member, Note, Progress, Question, Reaction


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


class BookAdminForm(forms.ModelForm):
    """Edits a book's listening time as "12h 30m", like the app's own form."""

    total_minutes = MinutesField(
        label="Total listening time", required=False, allow_zero=False
    )

    class Meta:
        model = Book
        fields = "__all__"


class ProgressAdminForm(forms.ModelForm):
    """Edits time listened as "4h 12m"; the stored value stays whole minutes."""

    minutes_read = MinutesField(label="Minutes read", required=False)

    class Meta:
        model = Progress
        fields = "__all__"


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    """Books can be added here until #14 builds the start and finish flows.

    No ``ordering`` here on purpose: it would override ``Book.Meta.ordering``
    and lose the explicit null placement on the two nullable dates.
    """

    form = BookAdminForm
    list_display = (
        "title",
        "author",
        "is_current",
        "started_on",
        "finished_on",
        "rating",
        "total_pages",
        "total_chapters",
        "listening_time",
    )
    list_filter = ("is_current",)
    search_fields = ("title", "author")

    @admin.display(description="Total listening time", ordering="total_minutes")
    def listening_time(self, obj):
        if obj.total_minutes is None:
            return "-"

        return format_minutes(obj.total_minutes)


@admin.register(Progress)
class ProgressAdmin(admin.ModelAdmin):
    """Correct a progress row by hand. Moves the current value without leaving
    a dot on the trail (decision #26)."""

    form = ProgressAdminForm
    list_display = ("member", "book", "how_far", "updated_on")
    list_select_related = ("member", "book")

    @admin.display(description="How far")
    def how_far(self, obj):
        units = obj.units_read

        if units is None:
            return "not started"

        return obj.book.describe_units(units, with_total=True)


@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    """Notes with their chapter anchor. Editing here is an admin's escape
    hatch; the app itself never edits a note (decision #7)."""

    list_display = ("book", "author", "chapter", "parent", "created_on")
    list_select_related = ("book", "author", "parent")


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("text", "book", "chapter", "position")
    list_select_related = ("book",)


@admin.register(Reaction)
class ReactionAdmin(admin.ModelAdmin):
    list_display = ("note", "member", "created_on")
    list_select_related = ("note", "member")
