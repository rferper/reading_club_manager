from django import forms

from .models import Member, Note, Progress, Question


class AdminPinForm(forms.Form):
    """The one field that opens admin mode.

    `PasswordInput` without `render_value`, so a failed attempt never echoes
    the submitted PIN back into the page. Decision #5: this is a speed bump,
    not security, but there is no reason to print the guess in the response.
    """

    pin = forms.CharField(
        label="Admin PIN",
        widget=forms.PasswordInput,
        max_length=64,
    )


class MemberForm(forms.ModelForm):
    """Add a member, or rename one. Admin-only either way.

    No `clean_name` here on purpose. `Member` already carries both
    `unique=True` and the case-insensitive `UniqueConstraint` from decision
    #13, and a `ModelForm` runs both, so a duplicate arrives as a field error
    and a case-only duplicate as a form-level one. Hand-rolling the check would
    duplicate the rule in a second place and let the two drift apart.

    `is_active` is deliberately absent: deactivating is a POST to
    `club:member_toggle`, not a checkbox someone can flip while renaming.
    """

    class Meta:
        model = Member
        fields = ("name", "role", "joined_on")
        labels = {
            "name": "Name",
            "role": "Role",
            "joined_on": "Joined on",
        }
        help_texts = {
            "role": "A label — \"Founder\", \"Host\". It confers nothing.",
            "joined_on": "Defaults to today. Backdate it for a founding member.",
        }
        widgets = {"joined_on": forms.DateInput(attrs={"type": "date"})}


class IdentityForm(forms.Form):
    """Pick your name off the roster.

    Anyone may pick anyone — decision #5. There is no password here and there
    is not going to be one; the point is attribution, so that a note has a name
    on it, not authentication.

    The queryset is filtered but not cached: it is re-evaluated on every render,
    so a member deactivated this morning is gone from the list this afternoon.
    """

    member = forms.ModelChoiceField(
        queryset=Member.objects.filter(is_active=True),
        label="Your name",
        empty_label="Pick your name",
    )


class ProgressForm(forms.ModelForm):
    """How far you have read.

    There is no member field and there never will be — decision #4. The view
    takes the member from the session, so this form cannot be used to post as
    somebody else, and nobody has to pick their own name twice.

    The upper bound belongs to the book rather than to the field, so it is
    checked here rather than declared on the model.
    """

    class Meta:
        model = Progress
        fields = ("pages_read",)
        labels = {"pages_read": "Pages read"}

    def __init__(self, *args, book, **kwargs):
        super().__init__(*args, **kwargs)
        self.book = book

        if book.total_pages:
            self.fields["pages_read"].help_text = f"Out of {book.total_pages}."
            self.fields["pages_read"].widget.attrs["max"] = book.total_pages
        else:
            self.fields["pages_read"].help_text = (
                "No page count is recorded for this book, so this shows as pages "
                "rather than a percentage."
            )

    def clean_pages_read(self):
        pages_read = self.cleaned_data["pages_read"]

        if self.book.total_pages and pages_read > self.book.total_pages:
            raise forms.ValidationError(
                f"{self.book.title} is only {self.book.total_pages} pages long."
            )

        return pages_read


class NoteForm(forms.ModelForm):
    """A thought about the current book.

    Body only. The author comes from the session and the book from what the
    club is reading — decisions #4 and #8 — so neither is a field somebody
    could submit.

    Django's form field strips surrounding whitespace, so a body of spaces
    arrives as "" and fails `required` without any check of its own.
    """

    class Meta:
        model = Note
        fields = ("body",)
        labels = {"body": "Your note"}
        widgets = {
            "body": forms.Textarea(
                attrs={"rows": 4, "placeholder": "I did not see that coming."}
            )
        }
        error_messages = {"body": {"required": "A note needs something in it."}}


class QuestionForm(forms.ModelForm):
    """A discussion prompt, and where it sits in the sequence.

    Admin-only. The book comes from what the club is reading, not from the
    form — decision #8 makes the foreign key explicit, but nothing lets the
    submitter choose it.
    """

    class Meta:
        model = Question
        fields = ("text", "position")
        labels = {"text": "Question", "position": "Position"}
        widgets = {"text": forms.Textarea(attrs={"rows": 3})}
        error_messages = {"text": {"required": "A question needs something in it."}}
