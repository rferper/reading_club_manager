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
