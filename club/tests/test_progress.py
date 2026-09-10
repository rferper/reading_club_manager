"""Recording how far a member has read, and the percentage derived from it."""

from datetime import date

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from ..models import Book, Member, Progress


class ProgressPercentTests(TestCase):
    """The derived number, and every boundary it has.

    Decision #1: pages are stored, the percentage is computed. These are the
    tests `_docs/testing-guidelines.md` calls the highest-value ones here.
    """

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.book = Book.objects.create(
            title="Middlemarch", author="George Eliot", total_pages=880
        )

    def _progress(self, pages_read, book=None):
        return Progress(book=book or self.book, member=self.ada, pages_read=pages_read)

    def test_the_percentage_is_derived_from_the_books_page_count(self):
        self.assertEqual(self._progress(440).percent, 50)

    def test_finishing_the_last_page_is_exactly_one_hundred(self):
        """Not 99 from a truncating division, and not 100.0000001."""
        self.assertEqual(self._progress(880).percent, 100)

    def test_nothing_read_is_zero_not_none(self):
        """Zero is a real answer and has to survive the template's `{% if %}`
        as a number, not as an empty state."""
        self.assertEqual(self._progress(0).percent, 0)

    def test_a_book_with_no_page_count_does_not_crash_the_calculation(self):
        """Decision #1 accepts this: the club sees raw pages instead. `None` is
        how the templates know which of the two to show."""
        no_count = Book.objects.create(title="Untitled", author="A")

        self.assertIsNone(self._progress(120, book=no_count).percent)

    def test_a_page_count_of_zero_is_treated_the_same_as_none(self):
        """A zero-page book is a typo, not a book. Dividing by it is worse."""
        zero = Book.objects.create(title="Zero", author="A", total_pages=0)

        self.assertIsNone(self._progress(0, book=zero).percent)

    def test_more_pages_than_the_book_has_is_capped_at_one_hundred(self):
        """Reachable when an admin corrects a page count downwards. A bar past
        its own track is a rendering bug, not information."""
        self.assertEqual(self._progress(1000).percent, 100)

    def test_no_percentage_is_stored_on_the_model(self):
        stored = {field.name for field in Progress._meta.get_fields()}

        self.assertIn("pages_read", stored)
        self.assertNotIn("percent", stored)


class ProgressModelTests(TestCase):
    """One row per member per book, and it is the database that says so."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.book = Book.objects.create(title="Middlemarch", author="George Eliot")

    def test_a_second_row_for_the_same_member_and_book_is_rejected(self):
        Progress.objects.create(book=self.book, member=self.ada, pages_read=10)

        with self.assertRaises(IntegrityError), transaction.atomic():
            Progress.objects.create(book=self.book, member=self.ada, pages_read=20)

    def test_the_same_member_may_have_progress_on_two_books(self):
        other = Book.objects.create(title="Piranesi", author="Susanna Clarke")
        Progress.objects.create(book=self.book, member=self.ada, pages_read=10)
        Progress.objects.create(book=other, member=self.ada, pages_read=20)

        self.assertEqual(self.ada.progress.count(), 2)

    def test_two_members_may_have_progress_on_the_same_book(self):
        bob = Member.objects.create(name="Bob")
        Progress.objects.create(book=self.book, member=self.ada, pages_read=10)
        Progress.objects.create(book=self.book, member=bob, pages_read=20)

        self.assertEqual(self.book.progress.count(), 2)

    def test_rows_come_back_furthest_along_first(self):
        """The order #10's overview reads in, set once on the model."""
        bob = Member.objects.create(name="Bob")
        behind = Progress.objects.create(book=self.book, member=self.ada, pages_read=10)
        ahead = Progress.objects.create(book=self.book, member=bob, pages_read=300)

        self.assertEqual(list(self.book.progress.all()), [ahead, behind])

    def test_a_duplicate_is_a_validation_error_before_it_is_an_integrity_error(self):
        Progress.objects.create(book=self.book, member=self.ada, pages_read=10)

        with self.assertRaises(ValidationError):
            Progress(book=self.book, member=self.ada, pages_read=20).full_clean()


class ProgressUpdateTests(TestCase):
    """The form, driven as a member would drive it."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.book = Book.objects.create(
            title="Middlemarch",
            author="George Eliot",
            total_pages=880,
            started_on=date(2025, 9, 1),
            is_current=True,
        )

    def setUp(self):
        session = self.client.session
        session["member_id"] = self.ada.pk
        session.save()

    def test_the_form_names_the_book_and_asks_for_pages(self):
        response = self.client.get(reverse("club:progress_update"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Middlemarch")
        self.assertContains(response, "Out of 880")
        self.assertContains(response, 'for="id_pages_read"')

    def test_opening_the_form_records_nothing(self):
        """A GET must not write. A member who looks and leaves has recorded
        nothing, and the overview shows them as zero either way."""
        self.client.get(reverse("club:progress_update"))

        self.assertEqual(Progress.objects.count(), 0)

    def test_submitting_records_progress_for_the_session_member(self):
        response = self.client.post(
            reverse("club:progress_update"), {"pages_read": "440"}, follow=True
        )

        self.assertRedirects(response, reverse("club:home"))
        progress = Progress.objects.get()
        self.assertEqual(progress.member, self.ada)
        self.assertEqual(progress.pages_read, 440)
        self.assertContains(response, "You are 440 pages in — 50%.")

    def test_the_form_carries_no_member_field(self):
        """Decision #4: identity is chosen once per session, so a form cannot
        be used to post as somebody else."""
        response = self.client.get(reverse("club:progress_update"))

        self.assertEqual(list(response.context["form"].fields), ["pages_read"])

    def test_a_submitted_member_field_is_ignored(self):
        bob = Member.objects.create(name="Bob")

        self.client.post(
            reverse("club:progress_update"),
            {"pages_read": "440", "member": bob.pk},
        )

        self.assertEqual(Progress.objects.get().member, self.ada)

    def test_submitting_twice_updates_the_row_rather_than_adding_one(self):
        self.client.post(reverse("club:progress_update"), {"pages_read": "100"})
        self.client.post(reverse("club:progress_update"), {"pages_read": "440"})

        self.assertEqual(Progress.objects.count(), 1)
        self.assertEqual(Progress.objects.get().pages_read, 440)

    def test_the_form_starts_from_what_was_last_recorded(self):
        Progress.objects.create(book=self.book, member=self.ada, pages_read=100)

        response = self.client.get(reverse("club:progress_update"))

        self.assertEqual(response.context["form"].initial["pages_read"], 100)
        self.assertContains(response, "You last recorded 100")

    def test_two_members_record_separately(self):
        bob = Member.objects.create(name="Bob")
        self.client.post(reverse("club:progress_update"), {"pages_read": "100"})

        session = self.client.session
        session["member_id"] = bob.pk
        session.save()
        self.client.post(reverse("club:progress_update"), {"pages_read": "300"})

        self.assertEqual(Progress.objects.count(), 2)
        self.assertEqual(Progress.objects.get(member=bob).pages_read, 300)


class ProgressBoundsTests(TestCase):
    """Numbers the form has to refuse on the page rather than store."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.book = Book.objects.create(
            title="Middlemarch", author="George Eliot", total_pages=880, is_current=True
        )

    def setUp(self):
        session = self.client.session
        session["member_id"] = self.ada.pk
        session.save()

    def test_more_pages_than_the_book_has_is_a_form_error(self):
        response = self.client.post(
            reverse("club:progress_update"), {"pages_read": "881"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "pages_read",
            "Middlemarch is only 880 pages long.",
        )
        self.assertEqual(Progress.objects.count(), 0)

    def test_the_last_page_itself_is_accepted(self):
        response = self.client.post(
            reverse("club:progress_update"), {"pages_read": "880"}
        )

        self.assertRedirects(response, reverse("club:home"))
        self.assertEqual(Progress.objects.get().percent, 100)

    def test_a_negative_number_is_a_form_error(self):
        response = self.client.post(
            reverse("club:progress_update"), {"pages_read": "-1"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Progress.objects.count(), 0)

    def test_a_book_with_no_page_count_accepts_any_number_of_pages(self):
        """There is nothing to check against. #17 is the chapter-based answer;
        until then the club types pages and sees pages."""
        self.book.total_pages = None
        self.book.save(update_fields=["total_pages"])

        response = self.client.post(
            reverse("club:progress_update"), {"pages_read": "5000"}, follow=True
        )

        self.assertEqual(Progress.objects.get().pages_read, 5000)
        self.assertContains(response, "You are 5000 pages in.")


class ChapterProgressTests(TestCase):
    """A book measured in chapters: same rules, a different denominator (#17).

    Decision #1 is untouched — the book still owns the scale, the member still
    records a count, and no percentage is stored anywhere.
    """

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.book = Book.objects.create(
            title="Piranesi",
            author="Susanna Clarke",
            total_chapters=30,
            started_on=date(2025, 9, 1),
            is_current=True,
        )

    def setUp(self):
        session = self.client.session
        session["member_id"] = self.ada.pk
        session.save()

    def test_units_read_reads_the_chapter_column(self):
        progress = Progress(
            book=self.book, member=self.ada, pages_read=431, chapters_read=12
        )

        self.assertEqual(progress.units_read, 12)

    def test_the_percentage_divides_by_the_chapter_count(self):
        progress = Progress(book=self.book, member=self.ada, chapters_read=15)

        self.assertEqual(progress.percent, 50)

    def test_the_form_asks_for_chapters_and_says_out_of_how_many(self):
        response = self.client.get(reverse("club:progress_update"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Chapters read")
        self.assertContains(response, "Out of 30")
        self.assertContains(response, 'for="id_chapters_read"')

    def test_the_form_offers_the_chapter_field_and_nothing_else(self):
        """Not the page field hidden — absent, so saving chapters cannot
        overwrite a page count recorded before the book changed measure."""
        response = self.client.get(reverse("club:progress_update"))

        self.assertEqual(list(response.context["form"].fields), ["chapters_read"])

    def test_submitting_records_chapters(self):
        response = self.client.post(
            reverse("club:progress_update"), {"chapters_read": "12"}, follow=True
        )

        self.assertRedirects(response, reverse("club:home"))
        progress = Progress.objects.get()
        self.assertEqual(progress.chapters_read, 12)
        self.assertEqual(progress.pages_read, 0)

    def test_the_message_names_the_unit_rather_than_a_bare_count(self):
        response = self.client.post(
            reverse("club:progress_update"), {"chapters_read": "12"}, follow=True
        )

        self.assertContains(response, "You are 12 chapters in — 40%.")

    def test_more_chapters_than_the_book_has_is_a_form_error(self):
        response = self.client.post(
            reverse("club:progress_update"), {"chapters_read": "31"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "chapters_read",
            "Piranesi is only 30 chapters long.",
        )
        self.assertEqual(Progress.objects.count(), 0)

    def test_the_last_chapter_itself_is_accepted(self):
        response = self.client.post(
            reverse("club:progress_update"), {"chapters_read": "30"}
        )

        self.assertRedirects(response, reverse("club:home"))
        self.assertEqual(Progress.objects.get().percent, 100)

    def test_an_unidentified_post_is_still_refused_rather_than_redirected(self):
        """Decision #16, guarded again now that the form has changed shape."""
        anonymous = self.client_class()

        response = anonymous.post(
            reverse("club:progress_update"), {"chapters_read": "12"}
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Progress.objects.count(), 0)

    def test_the_form_starts_from_the_chapters_last_recorded(self):
        Progress.objects.create(book=self.book, member=self.ada, chapters_read=9)

        response = self.client.get(reverse("club:progress_update"))

        self.assertEqual(response.context["form"].initial["chapters_read"], 9)
        self.assertContains(response, "You last recorded 9")
        self.assertContains(response, "chapters")

    def test_rows_come_back_furthest_along_first_in_chapters(self):
        """`Meta.ordering` used to name `pages_read`, which on this book is a
        column nobody writes to."""
        bob = Member.objects.create(name="Bob")
        behind = Progress.objects.create(
            book=self.book, member=self.ada, chapters_read=4
        )
        ahead = Progress.objects.create(book=self.book, member=bob, chapters_read=22)

        self.assertEqual(list(self.book.progress.all()), [ahead, behind])

    def test_the_ordering_ignores_pages_recorded_before_the_measure_changed(self):
        bob = Member.objects.create(name="Bob")
        stale = Progress.objects.create(
            book=self.book, member=self.ada, pages_read=431, chapters_read=0
        )
        recorded = Progress.objects.create(book=self.book, member=bob, chapters_read=2)

        self.assertEqual(list(self.book.progress.all()), [recorded, stale])

    def test_the_str_counts_in_the_books_own_unit(self):
        progress = Progress(book=self.book, member=self.ada, chapters_read=12)

        self.assertEqual(str(progress), "Ada — 12 chapters of Piranesi")


class ProgressMeasureChangeTests(TestCase):
    """The book that changes measure underneath the people reading it.

    Decision #19: nothing recorded and a recorded zero are different sentences,
    and so is a number recorded in a unit the club has stopped counting in.
    """

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.book = Book.objects.create(
            title="Middlemarch",
            author="George Eliot",
            total_pages=880,
            is_current=True,
        )
        cls.progress = Progress.objects.create(
            book=cls.book, member=cls.ada, pages_read=431
        )

    def setUp(self):
        session = self.client.session
        session["member_id"] = self.ada.pk
        session.save()

    def _switch_to_chapters(self):
        self.book.total_pages = None
        self.book.total_chapters = 30
        self.book.save(update_fields=["total_pages", "total_chapters"])

    def test_the_recorded_pages_are_not_rewritten(self):
        self._switch_to_chapters()
        self.progress.refresh_from_db()

        self.assertEqual(self.progress.pages_read, 431)
        self.assertIsNone(self.progress.chapters_read)

    def test_the_member_is_not_suddenly_431_chapters_in(self):
        """The whole reason `chapters_read` is a second column."""
        self._switch_to_chapters()
        progress = Progress.objects.select_related("book").get()

        self.assertIsNone(progress.units_read)
        self.assertIsNone(progress.percent)

    def test_re_recording_in_chapters_leaves_the_pages_alone(self):
        self._switch_to_chapters()

        self.client.post(reverse("club:progress_update"), {"chapters_read": "6"})

        progress = Progress.objects.get()
        self.assertEqual(progress.chapters_read, 6)
        self.assertEqual(progress.pages_read, 431)

    def test_a_submitted_page_count_cannot_reach_the_column(self):
        """The field is gone, not hidden, so a hand-typed `pages_read` on a
        chapter-measured book is ignored rather than stored."""
        self._switch_to_chapters()

        self.client.post(
            reverse("club:progress_update"),
            {"chapters_read": "6", "pages_read": "1"},
        )

        self.assertEqual(Progress.objects.get().pages_read, 431)


class ProgressWithNeitherCountTests(TestCase):
    """A book with no page count and no chapter count: the status quo."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.book = Book.objects.create(title="Untitled", author="A", is_current=True)

    def setUp(self):
        session = self.client.session
        session["member_id"] = self.ada.pk
        session.save()

    def test_the_form_still_asks_for_pages(self):
        response = self.client.get(reverse("club:progress_update"))

        self.assertContains(response, "Pages read")
        self.assertContains(response, "No page or chapter count is recorded")

    def test_any_number_is_accepted_and_the_message_names_pages(self):
        response = self.client.post(
            reverse("club:progress_update"), {"pages_read": "5000"}, follow=True
        )

        self.assertEqual(Progress.objects.get().pages_read, 5000)
        self.assertContains(response, "You are 5000 pages in.")


class ProgressWithNoCurrentBookTests(TestCase):
    """Between reads there is nothing to record against."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        Book.objects.create(
            title="Finished", author="A", finished_on=date(2025, 1, 1)
        )

    def setUp(self):
        session = self.client.session
        session["member_id"] = self.ada.pk
        session.save()

    def test_a_post_is_refused_and_stores_nothing(self):
        response = self.client.post(
            reverse("club:progress_update"), {"pages_read": "40"}, follow=True
        )

        self.assertRedirects(response, reverse("club:home"))
        self.assertContains(response, "There is no current book")
        self.assertEqual(Progress.objects.count(), 0)

    def test_the_form_is_not_offered(self):
        response = self.client.get(reverse("club:progress_update"), follow=True)

        self.assertRedirects(response, reverse("club:home"))
        self.assertContains(response, "There is no current book")

    def test_the_landing_page_does_not_link_to_it(self):
        response = self.client.get(reverse("club:home"))

        self.assertNotContains(response, reverse("club:progress_update"))


class ProgressIdentityTests(TestCase):
    """Nobody records progress as nobody."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.book = Book.objects.create(
            title="Middlemarch", author="George Eliot", total_pages=880, is_current=True
        )

    def test_an_unidentified_visitor_is_sent_to_the_picker_and_comes_back(self):
        response = self.client.get(reverse("club:progress_update"))

        self.assertRedirects(
            response,
            reverse("club:identify") + "?next=" + reverse("club:progress_update"),
            fetch_redirect_response=False,
        )

        session = self.client.session
        session["member_id"] = self.ada.pk
        session.save()

        self.assertEqual(
            self.client.get(reverse("club:progress_update")).status_code, 200
        )

    def test_an_unidentified_post_is_refused_rather_than_redirected(self):
        """Decision #16: a redirect would answer the POST with a GET and drop
        the number, while reading as success to anything automated."""
        response = self.client.post(
            reverse("club:progress_update"), {"pages_read": "440"}
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Progress.objects.count(), 0)

    def test_a_session_naming_a_deactivated_member_is_unidentified_again(self):
        self.ada.is_active = False
        self.ada.save(update_fields=["is_active"])
        session = self.client.session
        session["member_id"] = self.ada.pk
        session.save()

        response = self.client.post(
            reverse("club:progress_update"), {"pages_read": "440"}
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Progress.objects.count(), 0)
