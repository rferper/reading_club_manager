from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone


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

    started_on = models.DateField(null=True, blank=True)
    finished_on = models.DateField(null=True, blank=True)

    rating = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="1 to 5, agreed by the club when the book is finished.",
    )

    is_current = models.BooleanField(default=False)

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
                condition=models.Q(total_pages__isnull=True)
                | models.Q(total_chapters__isnull=True),
                name="book_has_one_denominator",
                violation_error_message=(
                    "A book is measured in pages or in chapters, not both."
                ),
            ),
        ]

    def __str__(self):
        return f"{self.title} by {self.author}"

    @property
    def measure(self):
        """What this book is measured in: ``"chapters"`` or ``"pages"``.

        Pages are the default, so a book with neither count behaves exactly as
        it always has. A chapter count of zero is a typo rather than a book —
        the same reading `percent_of` has always given a page count of zero —
        so it falls back to pages rather than measuring in nothing.

        Plural, because that is how every template and message uses it: "12 of
        30 chapters", "You are 440 pages in".
        """
        return "chapters" if self.total_chapters else "pages"

    @property
    def total_units(self):
        """The denominator this book carries, or ``None``.

        The one place the choice between the two columns is made for a book,
        so no caller has to make it again.
        """
        return self.total_chapters if self.measure == "chapters" else self.total_pages

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
    again updates the row; it does not add a second one. A member's progress
    over time would be a different model, and it is #18.

    ``chapters_read`` is a second column rather than a reuse of the first. A
    member who recorded 431 pages before the book switched to chapters must not
    silently become 431 chapters in: their pages stay where they are, they read
    as not started until they re-record, and nothing is rewritten. That is
    decision #19's distinction — nothing recorded and a recorded zero are
    different sentences — applied to a case it did not anticipate.

    It is nullable where ``pages_read`` defaults to zero, and that difference is
    the distinction itself. On a book that has always been measured in pages,
    the row's existence is what says somebody recorded something. On a book that
    changed measure, the row is already there and says nothing about chapters —
    so null means "not recorded in chapters" and zero means "I have the book and
    I am on chapter nought", which are the two sentences decision #19 keeps
    apart. Nothing rewrites ``pages_read`` to match; a book changing measure the
    other way is #21's conversion, not this column's problem.
    """

    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="progress")
    member = models.ForeignKey(
        Member, on_delete=models.CASCADE, related_name="progress"
    )
    pages_read = models.PositiveIntegerField(default=0)
    chapters_read = models.PositiveIntegerField(null=True, blank=True)
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
            f"{self.member} — {self.units_read} {self.book.measure} "
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
        return (
            self.chapters_read
            if self.book.measure == "chapters"
            else self.pages_read
        )

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

    body = models.TextField()
    created_on = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Newest first, which is the order the page reads in. `-pk` breaks the
        # tie between two notes saved inside the same clock tick.
        ordering = ["-created_on", "-pk"]

    def __str__(self):
        return f"{self.author} on {self.book.title}"

    def may_be_removed_by(self, member, is_admin):
        """Whether this viewer may remove this note — decision #7.

        A convention rather than a boundary (decision #5 again: anyone may pick
        any name), but the view enforces it anyway. Hiding the button is
        decoration; this is what the POST handler asks.
        """
        return bool(is_admin or (member is not None and member.pk == self.author_id))


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
