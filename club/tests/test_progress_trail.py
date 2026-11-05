"""One member's trail through one book — `/books/<pk>/progress/<member_pk>/`.

The page decision #26 exists for: `Progress` says where a member is now, and
this says how they got there. The awkward cases are most of the module —
nothing recorded, one data point, a number that went back down, a book with no
denominator, and a book that changed measure underneath everybody.
"""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format

from ..models import Book, Member, Progress, ProgressEntry


def record(progress, days_ago, **counts):
    """Append one entry, dated. `recorded_on` is `auto_now_add`, so the date is
    put back afterwards — the same thing the backfill has to do."""
    entry = ProgressEntry.objects.create(progress=progress, **counts)
    when = timezone.now() - timedelta(days=days_ago)
    ProgressEntry.objects.filter(pk=entry.pk).update(recorded_on=when)
    entry.refresh_from_db()
    return entry


class ProgressTrailTests(TestCase):
    """A real multi-week trail on a page-measured book."""

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
            book=cls.book, member=cls.ada, pages_read=604
        )
        record(cls.progress, 21, pages_read=120)
        record(cls.progress, 14, pages_read=311)
        record(cls.progress, 2, pages_read=604)

    def _get(self):
        return self.client.get(
            reverse("club:progress_trail", args=[self.book.pk, self.ada.pk])
        )

    def test_the_page_names_the_member_and_the_book(self):
        response = self._get()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ada")
        self.assertContains(response, "Middlemarch")

    def test_anyone_may_read_it_without_saying_who_they_are(self):
        """Public, like every other read in this app."""
        self.assertEqual(self._get().status_code, 200)

    def test_every_recorded_number_is_listed_newest_first(self):
        response = self._get()

        listed = [row["entry"].pages_read for row in response.context["rows"]]
        self.assertEqual(listed, [604, 311, 120])

    def test_each_count_carries_its_unit_and_the_books_total(self):
        """Never a bare number: "604" means nothing on its own."""
        self.assertContains(self._get(), "604 of 880 pages")

    def test_each_entry_shows_the_percentage_it_reached(self):
        response = self._get()

        self.assertContains(response, "69%")
        self.assertContains(response, "35%")

    def test_each_entry_draws_the_bar_the_design_system_already_defines(self):
        """A CSS width, not a plotted line — decision #26."""
        response = self._get()

        self.assertContains(response, "progress__fill")
        self.assertContains(response, "width: 69%")

    def test_the_bar_is_hidden_from_assistive_technology(self):
        """Decision #19: the number beside it carries the meaning."""
        self.assertContains(self._get(), 'aria-hidden="true"')

    def test_each_entry_after_the_first_names_the_change_in_pages(self):
        response = self._get()

        self.assertContains(response, "+293 pages")
        self.assertContains(response, "+191 pages")

    def test_each_entry_after_the_first_names_the_change_in_percent(self):
        response = self._get()

        self.assertContains(response, "+34%")
        self.assertContains(response, "+21%")

    def test_the_first_entry_gets_no_change_figure(self):
        """There is nothing behind it to have moved from."""
        rows = self._get().context["rows"]

        self.assertIsNone(rows[-1]["change"])
        self.assertIsNone(rows[-1]["percent_change"])

    def test_the_trail_is_dated(self):
        response = self._get()
        recorded_on = self.progress.entries.first().recorded_on

        self.assertContains(
            response,
            date_format(timezone.localtime(recorded_on), "DATETIME_FORMAT"),
        )

    def test_an_unknown_book_is_a_404(self):
        response = self.client.get(
            reverse("club:progress_trail", args=[self.book.pk + 99, self.ada.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_an_unknown_member_is_a_404(self):
        response = self.client.get(
            reverse("club:progress_trail", args=[self.book.pk, self.ada.pk + 99])
        )

        self.assertEqual(response.status_code, 404)

    def test_another_members_trail_on_the_same_book_does_not_leak_in(self):
        bo = Member.objects.create(name="Bo")
        bo_progress = Progress.objects.create(
            book=self.book, member=bo, pages_read=12
        )
        record(bo_progress, 1, pages_read=12)

        response = self.client.get(
            reverse("club:progress_trail", args=[self.book.pk, bo.pk])
        )

        listed = [row["entry"].pages_read for row in response.context["rows"]]
        self.assertEqual(listed, [12])

    def test_a_trail_on_another_book_does_not_leak_in(self):
        other = Book.objects.create(title="Piranesi", author="Clarke", total_pages=245)
        other_progress = Progress.objects.create(
            book=other, member=self.ada, pages_read=200
        )
        record(other_progress, 1, pages_read=200)

        listed = [row["entry"].pages_read for row in self._get().context["rows"]]
        self.assertEqual(listed, [604, 311, 120])


class ProgressTrailNothingRecordedTests(TestCase):
    """A member with no `Progress` row at all, so no entries either."""

    @classmethod
    def setUpTestData(cls):
        cls.dev = Member.objects.create(name="Dev")
        cls.book = Book.objects.create(
            title="Middlemarch", author="George Eliot", total_pages=880
        )

    def test_the_page_says_so_rather_than_showing_a_zero(self):
        """Decision #19: nothing recorded is not a recorded zero, and the
        design system says never a bare zero and never a blank region."""
        response = self.client.get(
            reverse("club:progress_trail", args=[self.book.pk, self.dev.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dev has not recorded anything on this one yet")

    def test_no_bar_is_drawn_at_all(self):
        response = self.client.get(
            reverse("club:progress_trail", args=[self.book.pk, self.dev.pk])
        )

        self.assertNotContains(response, "progress__fill")


class ProgressTrailOneEntryTests(TestCase):
    """Exactly one data point. One point draws no line."""

    @classmethod
    def setUpTestData(cls):
        cls.cleo = Member.objects.create(name="Cleo")
        cls.book = Book.objects.create(
            title="Middlemarch", author="George Eliot", total_pages=880
        )
        cls.progress = Progress.objects.create(
            book=cls.book, member=cls.cleo, pages_read=0
        )
        record(cls.progress, 5, pages_read=0)

    def _get(self):
        return self.client.get(
            reverse("club:progress_trail", args=[self.book.pk, self.cleo.pk])
        )

    def test_the_one_entry_is_shown(self):
        response = self._get()

        self.assertEqual(len(response.context["rows"]), 1)
        self.assertContains(response, "0 of 880 pages")

    def test_it_says_there_is_nothing_to_compare_it_to_yet(self):
        self.assertContains(self._get(), "nothing to compare it to yet")

    def test_no_change_figure_is_rendered(self):
        response = self._get()

        self.assertIsNone(response.context["rows"][0]["change"])
        self.assertNotContains(response, "trail__change")

    def test_a_recorded_zero_is_not_the_same_as_nothing_recorded(self):
        response = self._get()

        self.assertNotContains(response, "has not recorded anything")


class ProgressTrailGoingBackDownTests(TestCase):
    """A member who recorded a number and then a lower one."""

    @classmethod
    def setUpTestData(cls):
        cls.bo = Member.objects.create(name="Bo")
        cls.book = Book.objects.create(
            title="Middlemarch",
            author="George Eliot",
            total_pages=880,
            is_current=True,
        )
        cls.progress = Progress.objects.create(
            book=cls.book, member=cls.bo, pages_read=431
        )
        record(cls.progress, 10, pages_read=604)
        record(cls.progress, 3, pages_read=431)

    def _get(self):
        return self.client.get(
            reverse("club:progress_trail", args=[self.book.pk, self.bo.pk])
        )

    def test_both_entries_are_kept_in_order(self):
        listed = [row["entry"].pages_read for row in self._get().context["rows"]]

        self.assertEqual(listed, [431, 604])

    def test_the_decrease_reads_as_a_decrease(self):
        response = self._get()

        self.assertContains(response, "-173 pages")
        self.assertContains(response, "-20%")

    def test_the_overview_shows_the_lower_number_because_it_is_the_truth(self):
        response = self.client.get(reverse("club:progress"))

        self.assertContains(response, "431 of 880")
        self.assertNotContains(response, "604 of 880")


class ProgressTrailWithNoDenominatorTests(TestCase):
    """A book with no page count and no chapter count: no percentage to plot."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.book = Book.objects.create(title="Untitled", author="A")
        cls.progress = Progress.objects.create(
            book=cls.book, member=cls.ada, pages_read=120
        )
        record(cls.progress, 9, pages_read=40)
        record(cls.progress, 1, pages_read=120)

    def _get(self):
        return self.client.get(
            reverse("club:progress_trail", args=[self.book.pk, self.ada.pk])
        )

    def test_the_dated_counts_are_still_listed(self):
        response = self._get()

        self.assertContains(response, "120 pages")
        self.assertContains(response, "40 pages")

    def test_no_bar_is_drawn_at_zero_percent(self):
        """Never a bar at 0% — that would be a sentence nobody said."""
        self.assertNotContains(self._get(), "progress__fill")

    def test_it_says_why_there_is_no_percentage(self):
        self.assertContains(self._get(), "no page or chapter count recorded")

    def test_the_change_between_entries_is_still_named_in_pages(self):
        self.assertContains(self._get(), "+80 pages")

    def test_no_percentage_change_is_invented(self):
        rows = self._get().context["rows"]

        self.assertIsNone(rows[0]["percent_change"])


class ProgressTrailInChaptersTests(TestCase):
    """A chapter-measured book has a working trail of its own."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.book = Book.objects.create(
            title="The Left Hand of Darkness",
            author="Ursula K. Le Guin",
            total_chapters=30,
            finished_on=timezone.localdate(),
        )
        cls.progress = Progress.objects.create(
            book=cls.book, member=cls.ada, chapters_read=12
        )
        record(cls.progress, 12, chapters_read=4)
        record(cls.progress, 4, chapters_read=12)

    def _get(self):
        return self.client.get(
            reverse("club:progress_trail", args=[self.book.pk, self.ada.pk])
        )

    def test_each_count_names_chapters_rather_than_pages(self):
        self.assertContains(self._get(), "12 of 30 chapters")

    def test_the_percentage_divides_by_the_chapter_count(self):
        """Through `Book.percent_of()`, which is the only copy of it."""
        response = self._get()

        self.assertContains(response, "40%")
        self.assertEqual(response.context["rows"][0]["entry"].percent, 40)

    def test_the_change_is_named_in_chapters(self):
        self.assertContains(self._get(), "+8 chapters")

    def test_the_archive_entry_links_to_it(self):
        response = self.client.get(
            reverse("club:history_detail", args=[self.book.pk])
        )

        self.assertContains(
            response,
            reverse("club:progress_trail", args=[self.book.pk, self.ada.pk]),
        )


class ProgressTrailAfterAMeasureChangeTests(TestCase):
    """A book that was measured in pages and is now measured in chapters."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.book = Book.objects.create(
            title="The Left Hand of Darkness", author="Le Guin", total_pages=400
        )
        cls.progress = Progress.objects.create(
            book=cls.book, member=cls.ada, pages_read=200
        )
        record(cls.progress, 20, pages_read=90)
        record(cls.progress, 15, pages_read=200)

        # The club gives up on page numbers and the book changes measure.
        cls.book.total_pages = None
        cls.book.total_chapters = 20
        cls.book.save()

    def _get(self):
        return self.client.get(
            reverse("club:progress_trail", args=[self.book.pk, self.ada.pk])
        )

    def test_the_page_recorded_entries_are_not_read_against_chapters(self):
        """Decision #25: a number recorded on one scale is never readable
        against another. "200 of 20 chapters" is silent data corruption."""
        response = self._get()

        self.assertEqual(response.context["rows"], [])
        self.assertNotContains(response, "200 of 20")

    def test_it_says_the_earlier_entries_were_recorded_in_the_other_unit(self):
        """Not a blank page with no explanation."""
        response = self._get()

        self.assertContains(response, "recorded in pages")
        self.assertContains(response, "not on this trail")

    def test_the_entries_are_still_in_the_database(self):
        self.assertEqual(self.progress.entries.count(), 2)

    def test_re_recording_in_chapters_starts_the_trail_the_page_shows(self):
        self.progress.chapters_read = 6
        self.progress.record()

        response = self._get()

        self.assertEqual(len(response.context["rows"]), 1)
        self.assertContains(response, "6 of 20 chapters")
        self.assertContains(response, "recorded in pages")

    def test_a_first_chapter_entry_is_not_compared_with_a_page_entry(self):
        """+6 chapters over 200 pages is not a sentence."""
        self.progress.chapters_read = 6
        self.progress.record()

        rows = self._get().context["rows"]

        self.assertIsNone(rows[0]["change"])


class ProgressTrailForADeactivatedMemberTests(TestCase):
    """Decision #3: a member who leaves the club leaves the roster, not the
    record."""

    @classmethod
    def setUpTestData(cls):
        cls.zoe = Member.objects.create(name="Zoe", is_active=False)
        cls.ada = Member.objects.create(name="Ada")
        cls.book = Book.objects.create(
            title="Piranesi",
            author="Susanna Clarke",
            total_pages=245,
            finished_on=timezone.localdate(),
        )
        cls.progress = Progress.objects.create(
            book=cls.book, member=cls.zoe, pages_read=198
        )
        record(cls.progress, 30, pages_read=60)
        record(cls.progress, 22, pages_read=198)

    def test_the_page_renders_and_keeps_her_name(self):
        response = self.client.get(
            reverse("club:progress_trail", args=[self.book.pk, self.zoe.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Zoe")
        self.assertContains(response, "198 of 245 pages")

    def test_the_archive_links_to_it(self):
        response = self.client.get(
            reverse("club:history_detail", args=[self.book.pk])
        )

        self.assertContains(
            response,
            reverse("club:progress_trail", args=[self.book.pk, self.zoe.pk]),
        )

    def test_the_overview_does_not_because_it_lists_active_members_only(self):
        current = Book.objects.create(
            title="Middlemarch", author="Eliot", total_pages=880, is_current=True
        )
        Progress.objects.create(book=current, member=self.zoe, pages_read=100)
        Progress.objects.create(book=current, member=self.ada, pages_read=100)

        response = self.client.get(reverse("club:progress"))

        self.assertNotContains(
            response,
            reverse("club:progress_trail", args=[current.pk, self.zoe.pk]),
        )
        self.assertContains(
            response,
            reverse("club:progress_trail", args=[current.pk, self.ada.pk]),
        )


class ProgressTrailQueryCountTests(TestCase):
    """The N+1 this page would grow into if every dot asked for its own book."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.book = Book.objects.create(
            title="Middlemarch", author="George Eliot", total_pages=880
        )
        cls.progress = Progress.objects.create(
            book=cls.book, member=cls.ada, pages_read=1
        )

    def _add_entries(self, count):
        start = ProgressEntry.objects.count()
        for index in range(start, start + count):
            record(self.progress, count - index, pages_read=index + 1)

    def test_the_query_count_does_not_grow_with_the_trail(self):
        url = reverse("club:progress_trail", args=[self.book.pk, self.ada.pk])

        self._add_entries(3)
        with self.assertNumQueries(4):
            self.client.get(url)

        self._add_entries(27)
        with self.assertNumQueries(4):
            response = self.client.get(url)

        self.assertEqual(len(response.context["rows"]), 30)

    def test_the_four_queries_are_the_book_the_member_the_row_and_its_entries(self):
        """Pinned so the number above is a fact about this page rather than
        whatever it happened to be on the day it was written."""
        self._add_entries(3)

        with self.assertNumQueries(4):
            response = self.client.get(
                reverse("club:progress_trail", args=[self.book.pk, self.ada.pk])
            )

        self.assertEqual(len(response.context["rows"]), 3)


class ProgressTrailLinksTests(TestCase):
    """Getting to the page from the two lists that name a member and a book."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.current = Book.objects.create(
            title="Middlemarch",
            author="George Eliot",
            total_pages=880,
            is_current=True,
        )
        cls.finished = Book.objects.create(
            title="Piranesi",
            author="Susanna Clarke",
            total_pages=245,
            finished_on=timezone.localdate(),
        )
        Progress.objects.create(book=cls.current, member=cls.ada, pages_read=604)
        Progress.objects.create(book=cls.finished, member=cls.ada, pages_read=245)

    def test_the_overview_links_each_member_to_their_trail(self):
        response = self.client.get(reverse("club:progress"))

        self.assertContains(
            response,
            reverse("club:progress_trail", args=[self.current.pk, self.ada.pk]),
        )

    def test_the_archive_entry_links_each_row_to_that_members_trail(self):
        response = self.client.get(
            reverse("club:history_detail", args=[self.finished.pk])
        )

        self.assertContains(
            response,
            reverse("club:progress_trail", args=[self.finished.pk, self.ada.pk]),
        )

    def test_the_trail_links_back_to_the_book_it_belongs_to(self):
        response = self.client.get(
            reverse("club:progress_trail", args=[self.finished.pk, self.ada.pk])
        )

        self.assertContains(
            response, reverse("club:history_detail", args=[self.finished.pk])
        )


class ProgressTrailInMinutesTests(TestCase):
    """An audiobook's trail, with a pages-only legacy entry underneath it."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.book = Book.objects.create(
            title="Piranesi", author="Susanna Clarke", total_minutes=1300
        )
        cls.progress = Progress.objects.create(
            book=cls.book, member=cls.ada, minutes_read=150
        )
        record(cls.progress, 30, pages_read=200)
        record(cls.progress, 20, minutes_read=130)
        record(cls.progress, 10, minutes_read=195)
        record(cls.progress, 2, minutes_read=150)

    def _get(self):
        return self.client.get(
            reverse("club:progress_trail", args=[self.book.pk, self.ada.pk])
        )

    def test_only_minutes_entries_are_listed(self):
        listed = [row["entry"].minutes_read for row in self._get().context["rows"]]

        self.assertEqual(listed, [150, 195, 130])

    def test_the_pages_only_entry_is_counted_out_loud_in_its_own_unit(self):
        response = self._get()

        self.assertContains(response, "One earlier entry was")
        self.assertContains(response, "recorded in pages")
        self.assertContains(response, "measured in listening time")

    def test_each_entry_reads_as_time_of_the_total(self):
        response = self._get()

        self.assertContains(response, "3h 15m of 21h 40m")
        self.assertContains(response, "2h 10m of 21h 40m")
        self.assertNotContains(response, "195")
        self.assertNotContains(response, "1300")

    def test_changes_are_signed_time_and_percent(self):
        response = self._get()

        self.assertContains(response, "+1h 5m, +5%")
        self.assertContains(response, "-45m, -3%")

    def test_the_header_gives_the_total_as_time(self):
        self.assertContains(self._get(), "21h 40m")

    def test_it_is_still_four_queries(self):
        with self.assertNumQueries(4):
            self._get()


class ProgressTrailOfLegacyOnlyEntriesOnAMinutesBookTests(TestCase):
    """Nothing but pages on a book that is now measured in time."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.book = Book.objects.create(
            title="Piranesi", author="Susanna Clarke", total_minutes=1300
        )
        cls.progress = Progress.objects.create(
            book=cls.book, member=cls.ada, pages_read=200
        )
        record(cls.progress, 5, pages_read=100)
        record(cls.progress, 2, pages_read=200)

    def test_the_trail_counts_them_and_lists_none(self):
        response = self.client.get(
            reverse("club:progress_trail", args=[self.book.pk, self.ada.pk])
        )

        self.assertEqual(response.context["rows"], [])
        self.assertContains(response, "2 earlier entries were")
        self.assertContains(response, "recorded in pages")


class ProgressTrailBothOtherUnitsTests(TestCase):
    """Entries in two other units are both named."""

    def test_the_sentence_names_every_other_unit(self):
        ada = Member.objects.create(name="Ada")
        book = Book.objects.create(title="P", author="A", total_minutes=600)
        progress = Progress.objects.create(book=book, member=ada)
        record(progress, 5, pages_read=100)
        record(progress, 3, chapters_read=4)

        response = self.client.get(
            reverse("club:progress_trail", args=[book.pk, ada.pk])
        )

        self.assertContains(response, "recorded in pages and chapters")
