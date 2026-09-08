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
    """

    title = models.CharField(max_length=200)
    author = models.CharField(max_length=200)

    # Nullable: a club can start a book before anyone has checked the page
    # count, and progress then shows raw pages instead of a percentage.
    total_pages = models.PositiveIntegerField(null=True, blank=True)

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
        ]

    def __str__(self):
        return f"{self.title} by {self.author}"

    def percent_of(self, pages_read):
        """Whole percent of this book that ``pages_read`` covers, or ``None``.

        The one place the rule from decision #1 lives, because two pages read
        the same book: `Progress.percent` for a stored row, and the overview
        (#10), which annotates members with a page count and has no `Progress`
        instance to ask.

        ``None`` when the book has no page count — or a page count of zero,
        which is a typo rather than a book. The club sees raw pages then, which
        decision #1 accepts as a data-entry problem rather than a modelling one.

        Capped at 100: pages read can legitimately exceed the total after an
        admin corrects a page count downwards, and this number is a CSS bar
        width. A bar past its own track is a rendering bug, not information.
        """
        if not self.total_pages:
            return None

        return min(100, round(100 * pages_read / self.total_pages))


class Progress(models.Model):
    """How far one member has read one book.

    Pages are the stored truth and the percentage is derived (decision #1).
    Comparing members is the whole point of the feature, and that needs one
    common scale — two members can never disagree about what 50% of the same
    book is if neither of them stores it.

    One row per member per book, enforced in the database. Recording progress
    again updates the row; it does not add a second one. A member's progress
    over time would be a different model, and it is #18.
    """

    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="progress")
    member = models.ForeignKey(
        Member, on_delete=models.CASCADE, related_name="progress"
    )
    pages_read = models.PositiveIntegerField(default=0)
    updated_on = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "progress"
        # Furthest along first, then by name, which is the order #10's overview
        # reads in. Ties are common — everyone starts on zero.
        ordering = ["-pages_read", Lower("member__name")]
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
        return f"{self.member} — {self.pages_read} pages of {self.book.title}"

    @property
    def percent(self):
        """Whole percent of the book read, or ``None`` with no page count.

        Derived on every read, never stored — decision #1. The arithmetic lives
        on `Book`, so this row and the overview's annotated members cannot
        disagree about what half of the same book is.
        """
        return self.book.percent_of(self.pages_read)


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
