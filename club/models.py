from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models.functions import Lower
from django.utils import timezone

from .duration import format_minutes


# How each measure reads in a sentence about the unit itself ("recorded in
# pages, before this book was measured in listening time").
MEASURE_LABELS = {"pages": "pages", "chapters": "chapters", "minutes": "listening time"}


class Member(models.Model):
    """Someone in the club.

    Members are rows here, never Django ``User`` objects, and they are
    deactivated rather than deleted (decision #3) so that their notes and
    answers keep their attribution. ``role`` is a descriptive label and
    confers nothing (decision #10).
    """

    name = models.CharField(max_length=100, unique=True)
    role = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    joined_on = models.DateField(default=timezone.localdate)

    # When this member last pressed "Mark as seen" on the home page. Null means
    # never, and the panel then counts from the start of `joined_on`
    # (decision #31). Only that POST writes it; a page load never does.
    notifications_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = [Lower("name")]
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                name="member_name_unique_ci",
                violation_error_message="A member with that name already exists.",
            )
        ]

    def __str__(self):
        return self.name


class BookManager(models.Manager):
    def current(self):
        """The book the club is reading now, or ``None``.

        Between reads is a legitimate state (decision #2), not an error, so
        this returns ``None`` rather than raising. Every page that shows the
        current book has an empty state for exactly this.
        """
        return self.filter(is_current=True).first()


class Book(models.Model):
    """A book the club is reading, or has read.

    One model with a flag, not two tables (decision #2). Notes, questions,
    answers and progress all point at a book by foreign key, and finishing a
    book is the one operation that must not lose any of them — so finishing
    clears a flag rather than moving a row.

    ``total_pages`` exists so the progress percentage can be derived
    (decision #1). No percentage is ever stored. ``rating`` is club-level and
    recorded at finish time (decision #9).

    A book that nobody can page-match — an ebook, an audiobook, an edition the
    club does not share — declares ``total_chapters`` instead. At most one of
    the two, because two denominators is two answers to "how far is Ada", and
    decision #1 exists to make sure there is only ever one. ``measure`` and
    ``total_units`` are where that choice is read; ``total_pages`` and
    ``pages_read`` keep their honest names and keep holding pages.
    """

    title = models.CharField(max_length=200)
    author = models.CharField(max_length=200)

    # Nullable: a club can start a book before anyone has checked the page
    # count, and progress then shows raw pages instead of a percentage.
    total_pages = models.PositiveIntegerField(null=True, blank=True)

    # The other denominator, for a book whose pages nobody can agree on. Never
    # both at once — the constraint below refuses that everywhere, not only in
    # the form that remembered to ask.
    total_chapters = models.PositiveIntegerField(null=True, blank=True)

    # The third denominator, for an audiobook: total listening time in whole
    # minutes (decision #34). Shown everywhere as "Xh Ym", never as this number.
    total_minutes = models.PositiveIntegerField(null=True, blank=True)

    started_on = models.DateField(null=True, blank=True)
    finished_on = models.DateField(null=True, blank=True)

    rating = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="1 to 5, agreed by the club when the book is finished.",
    )

    is_current = models.BooleanField(default=False)

    # When the row was made, for "a new book started" (decision #31). The date
    # fields cannot say: `started_on` is optional and has no time.
    created_on = models.DateTimeField(auto_now_add=True)

    objects = BookManager()

    class Meta:
        # Newest-finished first, which is the order the archive wants. Both
        # dates are nullable, so the null placement is stated rather than left
        # to whatever the database happens to do.
        ordering = [
            models.F("finished_on").desc(nulls_last=True),
            models.F("started_on").desc(nulls_last=True),
            "-pk",
        ]
        constraints = [
            # A partial unique index: unique among the rows where the flag is
            # true, and silent about all the rows where it is false. In the
            # database rather than in a `save()` override, because the rule has
            # to hold against the admin, a fixture and a shell alike.
            models.UniqueConstraint(
                fields=["is_current"],
                condition=models.Q(is_current=True),
                name="only_one_current_book",
                violation_error_message=(
                    "Another book is already the club's current read."
                ),
            ),
            models.CheckConstraint(
                condition=models.Q(rating__isnull=True)
                | models.Q(rating__gte=1, rating__lte=5),
                name="book_rating_1_to_5",
                violation_error_message="A rating runs from 1 to 5.",
            ),
            # One denominator per book. In the database for the reason
            # decisions #2 and #17 give: a rule that lives only in the form
            # that remembered it is not a rule, and a fixture, a shell or a
            # future management command all walk straight past a form.
            models.CheckConstraint(
                condition=models.Q(
                    total_pages__isnull=True, total_chapters__isnull=True
                )
                | models.Q(total_pages__isnull=True, total_minutes__isnull=True)
                | models.Q(total_chapters__isnull=True, total_minutes__isnull=True),
                name="book_has_one_denominator",
                violation_error_message=(
                    "A book is measured in pages, chapters or listening time "
                    "- one of them, never more than one."
                ),
            ),
        ]

    def __str__(self):
        return f"{self.title} by {self.author}"

    @property
    def is_finished(self):
        """Whether the club has finished this book: not current, and dated.

        The one definition of "finished" that rating hangs on (decision #36).
        A book that is neither current nor dated is the abandoned shape
        `/history/` lists with "no finish date recorded" (decision #22).
        """
        return not self.is_current and self.finished_on is not None

    @property
    def measure(self):
        """What this book is measured in: ``"minutes"``, ``"chapters"`` or ``"pages"``.

        Pages are the default, so a book with neither count behaves exactly as
        it always has. A chapter count of zero is a typo rather than a book —
        the same reading `percent_of` has always given a page count of zero —
        so it falls back to pages rather than measuring in nothing.

        Plural, because that is how every template and message uses it: "12 of
        30 chapters", "You are 440 pages in".
        """
        if self.total_minutes:
            return "minutes"

        return "chapters" if self.total_chapters else "pages"

    TOTAL_COLUMNS = {
        "minutes": "total_minutes",
        "chapters": "total_chapters",
        "pages": "total_pages",
    }
    READ_COLUMNS = {
        "minutes": "minutes_read",
        "chapters": "chapters_read",
        "pages": "pages_read",
    }

    @property
    def total_units(self):
        """The denominator this book carries, or ``None``.

        The one place the choice between the columns is made for a book,
        so no caller has to make it again.
        """
        return getattr(self, self.TOTAL_COLUMNS[self.measure])

    @property
    def unit_column(self):
        """The `Progress` / `ProgressEntry` column this book is counted in."""
        return self.READ_COLUMNS[self.measure]

    def describe_units(self, units, *, with_total=False):
        """``units`` as a member reads it: "604 pages", "4h 12m".

        With ``with_total`` and a total on the book, "604 of 880 pages" and
        "4h 12m of 12h 30m". Minutes go through `format_minutes` and the raw
        count is never shown (decision #34).
        """
        if self.measure == "minutes":
            text = format_minutes(units)

            if with_total and self.total_units:
                text += f" of {format_minutes(self.total_units)}"

            return text

        if with_total and self.total_units:
            return f"{units} of {self.total_units} {self.measure}"

        return f"{units} {self.measure}"

    def describe_change(self, change):
        """A signed difference: "+293 pages", "-45m", "+1h 5m"."""
        sign = "+" if change > 0 else "-" if change < 0 else ""

        if self.measure == "minutes":
            return f"{sign}{format_minutes(abs(change))}"

        return f"{sign}{abs(change)} {self.measure}"

    def percent_of(self, units_read):
        """Whole percent of this book that ``units_read`` covers, or ``None``.

        The one place the rule from decision #1 lives, because two pages read
        the same book: `Progress.percent` for a stored row, and the overview
        (#10), which annotates members with a count and has no `Progress`
        instance to ask.

        ``None`` when the book has no page or chapter count — or a count of
        zero, which is a typo rather than a book. The club sees raw counts
        then, which decision #1 accepts as a data-entry problem rather than a
        modelling one.

        Capped at 100: units read can legitimately exceed the total after an
        admin corrects a count downwards, and this number is a CSS bar width.
        A bar past its own track is a rendering bug, not information.
        """
        total = self.total_units

        if not total:
            return None

        return min(100, round(100 * units_read / total))


class Progress(models.Model):
    """How far one member has read one book.

    Pages are the stored truth and the percentage is derived (decision #1).
    Comparing members is the whole point of the feature, and that needs one
    common scale — two members can never disagree about what 50% of the same
    book is if neither of them stores it.

    One row per member per book, enforced in the database. Recording progress
    again updates the row; it does not add a second one. How the member got
    here is a second model beside this one — `ProgressEntry`, appended by
    `record()` in the same transaction as the save (decision #26).

    ``chapters_read`` is a second column rather than a reuse of the first. A
    member who recorded 431 pages before the book switched to chapters must not
    silently become 431 chapters in: their pages stay where they are, they read
    as not started until they re-record, and nothing is rewritten. That is
    decision #19's distinction — nothing recorded and a recorded zero are
    different sentences — applied to a case it did not anticipate.

    Every count column is nullable (decision #39, which amends #25's first
    cut): null means "nothing recorded in this unit" and zero means "I have the
    book and I am on nought", which are the two sentences decision #19 keeps
    apart. Nothing rewrites one column to match another; converting a recorded
    number between units is #49, not these columns' problem.
    """

    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="progress")
    member = models.ForeignKey(
        Member, on_delete=models.CASCADE, related_name="progress"
    )
    # Nullable like the other two (decision #39): NULL is nothing recorded in
    # pages, 0 is a recorded zero.
    pages_read = models.PositiveIntegerField(null=True, blank=True)
    chapters_read = models.PositiveIntegerField(null=True, blank=True)

    # Whole minutes listened, nullable for the same reason as `chapters_read`
    # (decisions #25 and #34). Never written into either of the other two.
    minutes_read = models.PositiveIntegerField(null=True, blank=True)
    updated_on = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "progress"
        # Furthest along first, then by name, which is the order #10's overview
        # and the archive both read in. Ties are common — everyone starts on
        # zero.
        #
        # Which column "furthest" means is a fact about the book, so the
        # ordering asks the book rather than naming one column and being wrong
        # about every chapter-measured read. `> 0` rather than `IS NOT NULL`,
        # so this and `Book.measure` agree about a chapter count of zero.
        ordering = [
            models.Case(
                models.When(book__total_minutes__gt=0, then=models.F("minutes_read")),
                models.When(
                    book__total_chapters__gt=0, then=models.F("chapters_read")
                ),
                default=models.F("pages_read"),
            ).desc(nulls_last=True),
            Lower("member__name"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["book", "member"],
                name="one_progress_row_per_member_per_book",
                violation_error_message=(
                    "That member already has progress recorded on this book."
                ),
            )
        ]

    def __str__(self):
        if self.units_read is None:
            return f"{self.member} — nothing recorded on {self.book.title}"

        return (
            f"{self.member} — {self.book.describe_units(self.units_read)} "
            f"of {self.book.title}"
        )

    @property
    def units_read(self):
        """However far this member has read, in whatever the book measures in.

        Reads the column the book is measured in and leaves the other one
        alone. A page count recorded before the book changed measure is still
        there; it simply stops being the answer to "how far", and this answers
        ``None`` — nothing recorded — until the member says so in chapters.
        """
        return getattr(self, self.book.unit_column)

    @property
    def percent(self):
        """Whole percent of the book read, or ``None`` with nothing to divide.

        Derived on every read, never stored — decision #1. The arithmetic lives
        on `Book`, so this row and the overview's annotated members cannot
        disagree about what half of the same book is.

        ``None`` both when the book carries no count and when this member has
        recorded nothing in the unit it counts in.
        """
        if self.units_read is None:
            return None

        return self.book.percent_of(self.units_read)


    def record(self):
        """Save this row and append the entry that says when it got here.

        The one place both writes happen, and they happen together. `Progress`
        stays the answer to "where is this member now" and `ProgressEntry` is
        the record of how they got there (decision #26); two places holding the
        same number can only stay honest if one function writes both, inside
        one transaction.

        No `save()` override does this — decision #17. Recording progress is an
        act with a consequence, and the consequence is written where the act
        is, not hidden underneath it.

        An unchanged resubmission appends nothing: `updated_on` moves, because
        the member did say it again, but a trail is a record of movement and
        three identical dots from a double-clicked save are noise in the one
        place this exists to make readable.

        Returns the appended entry, or ``None`` when nothing moved.
        """
        column = self.book.unit_column
        units_read = getattr(self, column)

        with transaction.atomic():
            self.save()

            # Nothing has been recorded in the unit this book counts in, so
            # there is no number to put on the trail. Reachable only from the
            # shell: `ProgressForm` requires the field it asks for.
            if units_read is None:
                return None

            # The newest entry is the one that must match this row, so it is
            # the one worth comparing against — and comparing against it means
            # the two cannot silently drift apart either.
            latest = self.entries.first()

            if latest is not None and getattr(latest, column) == units_read:
                return None

            return self.entries.create(**{column: units_read})


class ProgressEntry(models.Model):
    """One number a member recorded against one book, and when.

    Appended only by `Progress.record()`, and beside `Progress` rather than instead of it (decision
    #26). `Progress` keeps its unique row per member per book and keeps meaning
    "where this member is now"; this is every value that row has ever held, so
    the club can read a member's trail through a book instead of only its end.

    Nothing edits an entry. The one thing that deletes one is the owner removing
    an older entry from their own trail on the current book
    (`progress_entry_delete`, decision #40); the newest entry is never
    removable, so the current value and the newest entry cannot disagree. An
    admin correcting a `Progress` row straight in `/admin/` still moves the
    current value without leaving a dot on the trail (#51).

    Two columns rather than one reused, for decision #25's reason exactly: a
    number recorded on one scale must never become readable against another.
    An entry carries one of them and never both — a `CheckConstraint` says so,
    so a fixture and a shell meet the rule as well as the view does.

    No percentage is stored here either (decision #1). `percent` derives it
    through `Book.percent_of()`, which stays the only place the arithmetic
    lives (decision #19).
    """

    progress = models.ForeignKey(
        Progress, on_delete=models.CASCADE, related_name="entries"
    )

    # Both nullable, unlike `Progress.pages_read`: an entry records the one
    # unit it was typed in and says nothing at all about the other, and the
    # constraint below is what makes "nothing at all" unambiguous.
    pages_read = models.PositiveIntegerField(null=True, blank=True)
    chapters_read = models.PositiveIntegerField(null=True, blank=True)
    minutes_read = models.PositiveIntegerField(null=True, blank=True)

    recorded_on = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "progress entries"
        # Newest first, which is the order the trail reads in. `-pk` breaks the
        # tie between two entries saved inside the same clock tick, the way
        # `Note` already does it.
        ordering = ["-recorded_on", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        pages_read__isnull=False,
                        chapters_read__isnull=True,
                        minutes_read__isnull=True,
                    )
                    | models.Q(
                        pages_read__isnull=True,
                        chapters_read__isnull=False,
                        minutes_read__isnull=True,
                    )
                    | models.Q(
                        pages_read__isnull=True,
                        chapters_read__isnull=True,
                        minutes_read__isnull=False,
                    )
                ),
                name="entry_counts_one_measure",
                violation_error_message=(
                    "An entry records pages, chapters or minutes - exactly "
                    "one of the three, never two and never none."
                ),
            )
        ]

    def __str__(self):
        if self.pages_read is not None:
            return f"{self.pages_read} pages on {self.recorded_on:%Y-%m-%d}"

        if self.minutes_read is not None:
            return (
                f"{format_minutes(self.minutes_read)} on {self.recorded_on:%Y-%m-%d}"
            )

        return f"{self.chapters_read} chapters on {self.recorded_on:%Y-%m-%d}"

    @property
    def units_read(self):
        """This entry's count, if it is in the unit the book measures in now.

        Exactly what `Progress.units_read` answers, and for the same reason:
        the column the book counts in is the answer and the other column is
        left alone. ``None`` when this entry was recorded before the book
        changed measure — it is still a true thing somebody typed, it is simply
        not on this trail.
        """
        return getattr(self, self.progress.book.unit_column)

    @property
    def percent(self):
        """Whole percent of the book this entry covers, or ``None``.

        Derived, never stored, and through `Book.percent_of()` — decisions #1
        and #19. There is no second copy of this arithmetic anywhere.
        """
        if self.units_read is None:
            return None

        return self.progress.book.percent_of(self.units_read)


class Note(models.Model):
    """One member's spontaneous thought about one book.

    Immutable by design (decision #7): a note is a timestamped reaction, and
    editing it after the fact rewrites the conversation that formed around it.
    It can be removed by its author or an admin, because the alternative to
    deleting a regretted note is not posting one.

    The book is a foreign key rather than "whatever is current" (decision #8),
    so the archive can replay a finished book's discussion.
    """

    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="notes")

    # PROTECT, not CASCADE: a member who leaves the club leaves the roster, not
    # the record (decision #3). Deactivating is the supported way out, and the
    # admin already refuses deletion; this is the second lock, in the schema,
    # where a fixture or a shell would otherwise walk straight past the first.
    author = models.ForeignKey(Member, on_delete=models.PROTECT, related_name="notes")

    # One level of replies (decision #28). Null for a top-level note. CASCADE:
    # a reply answers one note and reads as nonsense without it.
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="replies",
    )

    body = models.TextField()
    # Optional chapter this is about; null means not anchored. A label the
    # author chose, never checked against their own progress (decision #35).
    chapter = models.PositiveIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1)]
    )
    created_on = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Newest first, which is the order the page reads in. `-pk` breaks the
        # tie between two notes saved inside the same clock tick.
        ordering = ["-created_on", "-pk"]

    def __str__(self):
        return f"{self.author} on {self.book.title}"

    def clean(self):
        """A reply sits under a top-level note on the same book.

        Both rules compare this row to another row, which a `CheckConstraint`
        cannot do, so they live here and in `ReplyForm` — decision #28.
        """
        super().clean()

        parent = self.parent
        if parent is None:
            return

        if parent.parent_id is not None:
            raise ValidationError("A reply cannot be replied to.")

        if self.book_id is not None and parent.book_id != self.book_id:
            raise ValidationError("A reply belongs to the same book as its note.")

    def may_be_removed_by(self, member, is_admin):
        """Whether this viewer may remove this note — decision #7.

        A convention rather than a boundary (decision #5 again: anyone may pick
        any name), but the view enforces it anyway. Hiding the button is
        decoration; this is what the POST handler asks.
        """
        return bool(is_admin or (member is not None and member.pk == self.author_id))


class Reaction(models.Model):
    """One member's "Agree" on one top-level note (decision #42).

    One row per member per note, enforced in the database. Toggling adds or
    removes the row. CASCADE from the note, which it only decorates; PROTECT
    on the member, as for notes (decision #3, #20), so deactivated members'
    reactions keep counting.
    """

    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name="reactions")
    member = models.ForeignKey(
        Member, on_delete=models.PROTECT, related_name="reactions"
    )
    created_on = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["note", "member"], name="one_reaction_per_member_per_note"
            )
        ]

    def __str__(self):
        return f"{self.member} agrees with note {self.note_id}"


class Question(models.Model):
    """A discussion prompt the admin posts against a book.

    Admin-posted, not member-proposed — that is what `_docs/plan.md` says
    structured Q&A is. Members answer them in #13.

    The book is a foreign key (decision #8) so the archive can replay a past
    book's discussion, and the order is a field the admin sets rather than the
    order they happened to be typed in: a reading group's questions have a
    shape, and it is rarely chronological.
    """

    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="questions")
    text = models.TextField()
    position = models.PositiveIntegerField(
        default=1, help_text="Lower numbers come first. Ties fall back to age."
    )
    # Optional chapter this is about; null means not anchored. A label the
    # author chose, never checked against their own progress (decision #35).
    chapter = models.PositiveIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1)]
    )
    created_on = models.DateTimeField(auto_now_add=True)

    class Meta:
        # The admin's order, then age. Never creation time alone — #12 is
        # explicit that the sequence is a decision, not a side effect.
        ordering = ["position", "pk"]

    def __str__(self):
        return self.text



class Answer(models.Model):
    """One member's answer to one discussion question.

    One row per member per question, enforced in the database (decision #6).
    An answer is a standing position rather than a remark, so answering again
    updates it in place — ten rows from one person on one question is noise,
    and a uniqueness constraint without an update path is an integrity error
    waiting for the first person who changes their mind.

    Editable by its author, unlike a note (decision #7): refining a position on
    a fixed question is the point of asking one.
    """

    question = models.ForeignKey(
        Question, on_delete=models.CASCADE, related_name="answers"
    )

    # PROTECT for the same reason as `Note.author` — decision #20.
    member = models.ForeignKey(
        Member, on_delete=models.PROTECT, related_name="answers"
    )

    body = models.TextField()
    created_on = models.DateTimeField(auto_now_add=True)
    updated_on = models.DateTimeField(auto_now=True)

    class Meta:
        # Oldest first: the order the conversation actually happened in, which
        # is what a reader of the archive wants.
        ordering = ["created_on", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["question", "member"],
                name="one_answer_per_member_per_question",
                violation_error_message=(
                    "You have already answered this one — edit that answer instead."
                ),
            )
        ]

    def __str__(self):
        return f"{self.member} on {self.question.text[:40]}"

    @property
    def was_edited(self):
        """Whether this answer has changed since it was first written.

        Both timestamps are set on the first save, and `auto_now` has a coarser
        resolution than the gap between two fields of one INSERT, so this asks
        whether they differ by a real interval rather than at all.
        """
        return (self.updated_on - self.created_on).total_seconds() > 1


class AnswerReply(models.Model):
    """A remark on one answer, one level deep (decision #43).

    Its own model rather than a generalised `Note.parent`: an answer hangs off
    a question, not a book, and an answer is never a reply, so the one-level
    rule is structural and needs no `clean()`. Immutable like a note
    (decision #7), so there is no `updated_on`. Editing the answer it answers
    keeps the same row and so keeps its replies.
    """

    answer = models.ForeignKey(
        Answer, on_delete=models.CASCADE, related_name="replies"
    )

    # PROTECT for the reason in decision #20.
    author = models.ForeignKey(
        Member, on_delete=models.PROTECT, related_name="answer_replies"
    )

    body = models.TextField()
    created_on = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Oldest first: a conversation reads downward.
        ordering = ["created_on", "pk"]
        verbose_name_plural = "answer replies"

    def __str__(self):
        return f"{self.author} replying to {self.answer.member}"

    def may_be_removed_by(self, member, is_admin):
        """The author or an admin, the same rule as a note (decision #7)."""
        return bool(is_admin or (member is not None and member.pk == self.author_id))


class MemberRating(models.Model):
    """One member's score out of five for one book.

    Not the same thing as `Book.rating`, and not derived from it. Decision #9
    made that a single number the club agreed on out loud when it closed the
    book; this is what each member privately thought, and the archive shows the
    spread beside the agreement.

    One row per member per book, updated in place — the same shape decision #6
    settled for answers, and for the same reason: a score is a standing
    position, not a remark.

    You rate a book you have finished. The view enforces that; nothing here
    does, because a book's finished state is a fact about the book and moving
    it is #21's problem, not a reason to invalidate everybody's scores.
    """

    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="ratings")

    # PROTECT, for the reason in decision #20: a member who leaves the club
    # leaves the roster, not the record. Their score stays in the average.
    member = models.ForeignKey(
        Member, on_delete=models.PROTECT, related_name="ratings"
    )

    score = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    updated_on = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = [Lower("member__name")]
        constraints = [
            models.UniqueConstraint(
                fields=["book", "member"],
                name="one_rating_per_member_per_book",
                violation_error_message=(
                    "You have already rated this one — change that score instead."
                ),
            ),
            models.CheckConstraint(
                condition=models.Q(score__gte=1, score__lte=5),
                name="member_rating_1_to_5",
                violation_error_message="A rating runs from 1 to 5.",
            ),
        ]

    def __str__(self):
        return f"{self.member} rated {self.book.title} {self.score}"
