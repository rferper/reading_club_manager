from django import forms

from .models import Book, Member, Note, Progress, Question


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
    """How far you have read, in whatever the book is measured in.

    There is no member field and there never will be — decision #4. The view
    takes the member from the session, so this form cannot be used to post as
    somebody else, and nobody has to pick their own name twice.

    One field, chosen by the book: a page-measured book asks for pages and a
    chapter-measured one asks for chapters (#17). The other column is dropped
    rather than hidden, so a member recording chapters cannot touch the pages
    they recorded before the book changed measure.

    The upper bound belongs to the book rather than to the field, so it is
    checked here rather than declared on the model.
    """

    class Meta:
        model = Progress
        fields = ("pages_read", "chapters_read")
        labels = {"pages_read": "Pages read", "chapters_read": "Chapters read"}

    def __init__(self, *args, book, **kwargs):
        super().__init__(*args, **kwargs)
        self.book = book

        # `Book.measure` is the one place this choice is made. The field that
        # does not apply is removed outright: `construct_instance` skips what
        # is not in `cleaned_data`, so the other column keeps whatever it held.
        self.unit_field = (
            "chapters_read" if book.measure == "chapters" else "pages_read"
        )
        del self.fields[
            "pages_read" if self.unit_field == "chapters_read" else "chapters_read"
        ]

        field = self.fields[self.unit_field]
        # `chapters_read` is nullable on the model, so that a row carrying only
        # a page count from before the measure changed reads as nothing
        # recorded. Submitting the form is the member saying otherwise, so a
        # blank here is a missing answer rather than an erasure.
        field.required = True

        if book.total_units:
            field.help_text = f"Out of {book.total_units}."
            field.widget.attrs["max"] = book.total_units
        else:
            field.help_text = (
                "No page or chapter count is recorded for this book, so this "
                "shows as pages rather than a percentage."
            )

    def clean(self):
        cleaned_data = super().clean()
        units_read = cleaned_data.get(self.unit_field)
        total = self.book.total_units

        if units_read is not None and total and units_read > total:
            self.add_error(
                self.unit_field,
                f"{self.book.title} is only {total} {self.book.measure} long.",
            )

        return cleaned_data


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


class AnswerForm(forms.Form):
    """Your answer to one of the current book's questions.

    A plain `Form` rather than a `ModelForm`: the view writes through
    `update_or_create` (decision #6), so there is no instance to bind and no
    `save()` to call. The member is never a field — decision #4.

    `question` is a hidden `ModelChoiceField` over the questions that are open
    for answers, which is how a question on a finished book, a deleted one, or
    a hand-typed id all arrive as one form error instead of three code paths.
    """

    body = forms.CharField(
        label="Your answer",
        widget=forms.Textarea(attrs={"rows": 3}),
        error_messages={"required": "An answer needs something in it."},
    )

    def __init__(self, *args, questions, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["question"] = forms.ModelChoiceField(
            queryset=questions,
            widget=forms.HiddenInput,
            error_messages={
                "invalid_choice": "That question is not open for answers.",
                "required": "That question is not open for answers.",
            },
        )


class BookForm(forms.ModelForm):
    """Start a book. Admin-only.

    `is_current` is absent: the view sets it, because starting a book is an
    act with a rule attached (at most one) and not a checkbox. Decision #17
    says the same about why no `save()` override guards it.
    """

    class Meta:
        model = Book
        fields = ("title", "author", "total_pages", "total_chapters", "started_on")
        labels = {
            "title": "Title",
            "author": "Author",
            "total_pages": "Total pages",
            "total_chapters": "Total chapters",
            "started_on": "Started on",
        }
        help_texts = {
            "total_pages": "Optional. Without it, progress shows pages and no percentage.",
            "total_chapters": (
                "For a book whose pages nobody can agree on — an ebook, an "
                "audiobook, an edition the club does not share. One or the "
                "other, never both."
            ),
        }
        widgets = {"started_on": forms.DateInput(attrs={"type": "date"})}

    def clean(self):
        """One denominator per book, said on the page as well as in the schema.

        The `CheckConstraint` refuses this everywhere (decision #17's reason for
        putting rules in the database), and a constraint message cannot say
        which of the two to keep. This one can, and it attaches to the field the
        club is most likely to be adding.
        """
        cleaned_data = super().clean()

        if cleaned_data.get("total_pages") and cleaned_data.get("total_chapters"):
            self.add_error(
                "total_chapters",
                "A book is measured in pages or in chapters, not both. Keep the "
                "pages if the club shares an edition, and the chapters if it "
                "does not — then clear the other.",
            )

        return cleaned_data


class BookEditForm(BookForm):
    """Correct an archived book's metadata. Admin-only.

    Adds the two fields that only mean anything once a book is finished. Still
    no `is_current`: moving the flag is `book_start` and `book_finish`, which
    is where the rule about there being one of them lives.
    """

    class Meta(BookForm.Meta):
        fields = BookForm.Meta.fields + ("finished_on", "rating")
        labels = {
            **BookForm.Meta.labels,
            "finished_on": "Finished on",
            "rating": "Rating",
        }
        widgets = {
            **BookForm.Meta.widgets,
            "finished_on": forms.DateInput(attrs={"type": "date"}),
            "rating": forms.NumberInput(attrs={"min": 1, "max": 5}),
        }


class BookFinishForm(forms.ModelForm):
    """Close a book: the date the club finished it, and what they made of it.

    One rating for the club, recorded here — decision #9. A per-member rating
    is #16.
    """

    class Meta:
        model = Book
        fields = ("finished_on", "rating")
        labels = {"finished_on": "Finished on", "rating": "Rating"}
        help_texts = {"rating": "Optional. 1 to 5, as the club agreed it."}
        widgets = {
            "finished_on": forms.DateInput(attrs={"type": "date"}),
            # The model's validators already refuse anything outside 1-5. These
            # put the same bounds on the spinner, so the browser stops it
            # before the round trip does.
            "rating": forms.NumberInput(attrs={"min": 1, "max": 5}),
        }
        error_messages = {
            "finished_on": {"required": "A finished book needs the date it was finished."}
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Nullable on the model, because a book being read has no finish date.
        # Required here, because this form is the moment it gets one.
        self.fields["finished_on"].required = True


class MemberRatingForm(forms.Form):
    """Your own score out of five for a book the club has finished.

    A plain `Form`, like `AnswerForm` and for the same reason: the view writes
    through `update_or_create` (the shape decision #6 settled), so there is no
    instance to bind. Neither the member nor the book is a field — the member
    comes from the session, the book from the URL.
    """

    score = forms.TypedChoiceField(
        label="Your rating",
        coerce=int,
        choices=[(n, f"{n} out of 5") for n in range(1, 6)],
        error_messages={"invalid_choice": "A rating runs from 1 to 5."},
    )
