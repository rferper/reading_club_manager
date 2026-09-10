"""The `Book` model: one row for the current read and every past one."""

from datetime import date

from django.contrib.auth.models import User
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from ..forms import BookEditForm, BookForm
from ..models import Book


class BookModelTests(TestCase):
    """The row that is both the current read and every past one."""

    def test_a_book_needs_only_a_title_and_an_author(self):
        """Everything else arrives later: the page count when somebody checks
        it, the finish date and rating when the club is done."""
        book = Book.objects.create(title="Middlemarch", author="George Eliot")

        self.assertIsNone(book.total_pages)
        self.assertIsNone(book.started_on)
        self.assertIsNone(book.finished_on)
        self.assertIsNone(book.rating)
        self.assertIs(book.is_current, False)

    def test_str_names_the_book_and_who_wrote_it(self):
        book = Book(title="Middlemarch", author="George Eliot")

        self.assertEqual(str(book), "Middlemarch by George Eliot")

    def test_books_are_ordered_newest_finished_first(self):
        older = Book.objects.create(
            title="Older", author="A", finished_on=date(2024, 1, 1)
        )
        newer = Book.objects.create(
            title="Newer", author="B", finished_on=date(2025, 6, 1)
        )

        self.assertEqual(list(Book.objects.all()), [newer, older])

    def test_an_unfinished_book_sorts_after_every_finished_one(self):
        """`nulls_last` is stated rather than inherited: the archive lists
        finished books, and a null finish date must not lead it."""
        finished = Book.objects.create(
            title="Finished", author="A", finished_on=date(2024, 1, 1)
        )
        reading = Book.objects.create(title="Reading", author="B", is_current=True)

        self.assertEqual(list(Book.objects.all()), [finished, reading])

    def test_no_percentage_is_stored_anywhere_on_the_book(self):
        """Decision #1: `total_pages` is here so a percentage can be derived,
        and that is the only place a percentage may come from."""
        field_names = {field.name for field in Book._meta.get_fields()}

        self.assertIn("total_pages", field_names)
        self.assertNotIn("percent", field_names)
        self.assertNotIn("percentage", field_names)


class CurrentBookTests(TestCase):
    """At most one current read, and no current read at all, both supported."""

    def test_no_current_book_is_a_supported_state(self):
        """Decision #2: the club sits between reads. `current()` answers that
        with None rather than raising, so every page can have an empty state."""
        Book.objects.create(title="Finished", author="A", finished_on=date(2024, 1, 1))

        self.assertIsNone(Book.objects.current())

    def test_current_returns_the_flagged_book(self):
        Book.objects.create(title="Finished", author="A", finished_on=date(2024, 1, 1))
        reading = Book.objects.create(title="Reading", author="B", is_current=True)

        self.assertEqual(Book.objects.current(), reading)

    def test_a_second_current_book_is_rejected_by_the_database(self):
        """A convention would hold only for the code that remembered it. This
        has to hold against the admin, a fixture and a shell alike."""
        Book.objects.create(title="First", author="A", is_current=True)

        with self.assertRaises(IntegrityError), transaction.atomic():
            Book.objects.create(title="Second", author="B", is_current=True)

    def test_a_second_current_book_is_a_validation_error_before_that(self):
        Book.objects.create(title="First", author="A", is_current=True)

        with self.assertRaises(ValidationError) as caught:
            Book(title="Second", author="B", is_current=True).full_clean()

        self.assertIn(
            "Another book is already the club's current read.",
            caught.exception.message_dict[NON_FIELD_ERRORS],
        )

    def test_any_number_of_books_may_be_not_current(self):
        """The index is partial: it says nothing about the rows with the flag
        off, which is every book the club has ever finished."""
        for title in ("One", "Two", "Three"):
            Book.objects.create(title=title, author="A")

        self.assertEqual(Book.objects.filter(is_current=False).count(), 3)

    def test_the_flag_can_move_from_one_book_to_the_next(self):
        """What #14's finish flow will do: clear the old one, set the new one."""
        first = Book.objects.create(title="First", author="A", is_current=True)

        with transaction.atomic():
            first.is_current = False
            first.finished_on = date(2025, 1, 1)
            first.save()
            second = Book.objects.create(title="Second", author="B", is_current=True)

        self.assertEqual(Book.objects.current(), second)


class BookRatingTests(TestCase):
    """One club-level rating, 1 to 5, recorded at finish time — decision #9."""

    def test_a_rating_inside_the_range_is_accepted(self):
        for rating in (1, 3, 5):
            with self.subTest(rating=rating):
                book = Book(title=f"Book {rating}", author="A", rating=rating)
                book.full_clean()

    def test_a_rating_outside_the_range_is_rejected(self):
        for rating in (0, 6):
            with self.subTest(rating=rating):
                with self.assertRaises(ValidationError) as caught:
                    Book(title="Book", author="A", rating=rating).full_clean()

                self.assertIn("rating", caught.exception.message_dict)

    def test_the_range_is_enforced_by_the_database_too(self):
        """Validators run in forms; the check constraint runs everywhere."""
        with self.assertRaises(IntegrityError), transaction.atomic():
            Book.objects.create(title="Book", author="A", rating=9)

    def test_an_unrated_book_is_fine(self):
        book = Book.objects.create(title="Book", author="A")

        self.assertIsNone(book.rating)


class BookMeasureTests(TestCase):
    """The denominator: pages, chapters, or neither — but never both.

    #17. Decision #1 says the book owns the scale everyone is compared on, and
    a chapter count is a second way of writing that scale down, not a second
    scale.
    """

    def test_a_book_with_a_page_count_measures_in_pages(self):
        book = Book(title="Middlemarch", author="George Eliot", total_pages=880)

        self.assertEqual(book.measure, "pages")
        self.assertEqual(book.total_units, 880)

    def test_a_book_with_a_chapter_count_measures_in_chapters(self):
        book = Book(title="Piranesi", author="Susanna Clarke", total_chapters=30)

        self.assertEqual(book.measure, "chapters")
        self.assertEqual(book.total_units, 30)

    def test_a_book_with_neither_count_measures_in_pages_and_has_no_total(self):
        """The status quo, unchanged: raw pages, no percentage, no bound."""
        book = Book(title="Untitled", author="A")

        self.assertEqual(book.measure, "pages")
        self.assertIsNone(book.total_units)

    def test_the_percentage_divides_by_the_chapter_count(self):
        book = Book(title="Piranesi", author="Susanna Clarke", total_chapters=30)

        self.assertEqual(book.percent_of(15), 50)
        self.assertEqual(book.percent_of(30), 100)

    def test_more_chapters_than_the_book_has_is_capped_at_one_hundred(self):
        """Decision #18, generalised rather than replaced."""
        book = Book(title="Piranesi", author="Susanna Clarke", total_chapters=30)

        self.assertEqual(book.percent_of(44), 100)

    def test_a_chapter_count_of_zero_is_treated_as_no_count_at_all(self):
        """A zero-chapter book is a typo, not a book — the same reading a
        page count of zero has always had."""
        book = Book(title="Zero", author="A", total_chapters=0)

        self.assertEqual(book.measure, "pages")
        self.assertIsNone(book.total_units)
        self.assertIsNone(book.percent_of(3))

    def test_both_counts_at_once_is_rejected_by_the_database(self):
        """The house pattern from decisions #2 and #17: a fixture and a shell
        meet the rule too, not only the form that remembered it."""
        with self.assertRaises(IntegrityError), transaction.atomic():
            Book.objects.create(
                title="Both", author="A", total_pages=880, total_chapters=30
            )

    def test_both_counts_at_once_is_a_validation_error_before_that(self):
        with self.assertRaises(ValidationError) as caught:
            Book(
                title="Both", author="A", total_pages=880, total_chapters=30
            ).full_clean()

        self.assertIn(
            "A book is measured in pages or in chapters, not both.",
            caught.exception.message_dict[NON_FIELD_ERRORS],
        )

    def test_either_count_on_its_own_is_fine(self):
        for field, value in (("total_pages", 880), ("total_chapters", 30)):
            with self.subTest(field=field):
                book = Book(title=f"Book {field}", author="A", **{field: value})
                book.full_clean()
                book.save()

    def test_no_percentage_is_stored_against_the_chapter_count_either(self):
        field_names = {field.name for field in Book._meta.get_fields()}

        self.assertIn("total_chapters", field_names)
        self.assertNotIn("percent", field_names)


class BookDenominatorFormTests(TestCase):
    """The same rule, said on the page where a typo actually arrives."""

    def test_the_start_form_offers_both_counts_and_explains_the_second(self):
        form = BookForm()

        self.assertIn("total_chapters", form.fields)
        self.assertIn("nobody can agree", form.fields["total_chapters"].help_text)

    def test_the_start_form_refuses_both_counts_at_once(self):
        form = BookForm(
            {
                "title": "Both",
                "author": "A",
                "total_pages": "880",
                "total_chapters": "30",
                "started_on": "",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("total_chapters", form.errors)
        self.assertIn("pages or in chapters", str(form.errors["total_chapters"]))

    def test_the_edit_form_refuses_both_counts_at_once(self):
        book = Book.objects.create(title="Piranesi", author="A", total_chapters=30)
        form = BookEditForm(
            {
                "title": "Piranesi",
                "author": "A",
                "total_pages": "245",
                "total_chapters": "30",
                "started_on": "",
                "finished_on": "",
                "rating": "",
            },
            instance=book,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("total_chapters", form.errors)

    def test_a_chapter_count_on_its_own_is_accepted(self):
        form = BookForm(
            {
                "title": "Piranesi",
                "author": "Susanna Clarke",
                "total_pages": "",
                "total_chapters": "30",
                "started_on": "",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save(commit=False).total_units, 30)


class BookAdminTests(TestCase):
    """The only place books can be entered until #14 builds start and finish."""

    @classmethod
    def setUpTestData(cls):
        cls.superuser = User.objects.create_superuser(
            username="root", email="root@example.com", password="not-a-real-password"
        )
        cls.book = Book.objects.create(
            title="Middlemarch",
            author="George Eliot",
            total_pages=880,
            started_on=date(2025, 9, 1),
            is_current=True,
        )

    def setUp(self):
        self.client.force_login(self.superuser)

    def test_the_changelist_shows_the_columns_the_club_needs(self):
        response = self.client.get(reverse("admin:club_book_changelist"))

        self.assertEqual(response.status_code, 200)
        # The leading entry is Django's own action checkbox, which is here
        # because books, unlike members, may be deleted.
        self.assertEqual(
            tuple(response.context["cl"].list_display)[-8:],
            (
                "title",
                "author",
                "is_current",
                "started_on",
                "finished_on",
                "rating",
                "total_pages",
                "total_chapters",
            ),
        )
        self.assertContains(response, "Middlemarch")

    def test_a_superuser_can_add_a_book(self):
        response = self.client.post(
            reverse("admin:club_book_add"),
            {
                "title": "Piranesi",
                "author": "Susanna Clarke",
                "total_pages": "245",
                "started_on": "",
                "finished_on": "",
                "rating": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Book.objects.get(title="Piranesi").total_pages, 245)

    def test_marking_a_second_book_current_is_a_form_error_not_a_500(self):
        response = self.client.post(
            reverse("admin:club_book_add"),
            {
                "title": "Piranesi",
                "author": "Susanna Clarke",
                "total_pages": "",
                "started_on": "",
                "finished_on": "",
                "rating": "",
                "is_current": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Another book is already the club&#x27;s current read.")
        self.assertEqual(Book.objects.filter(is_current=True).count(), 1)
