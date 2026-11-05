"""The group overview: who is ahead, who is behind, and who has not started."""

import re
from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from ..models import Book, Member, Progress, ProgressEntry


class ProgressOverviewTests(TestCase):
    """The table itself."""

    @classmethod
    def setUpTestData(cls):
        cls.book = Book.objects.create(
            title="Middlemarch",
            author="George Eliot",
            total_pages=880,
            started_on=date(2025, 9, 1),
            is_current=True,
        )
        cls.ada = Member.objects.create(name="Ada")
        cls.bob = Member.objects.create(name="Bob")
        cls.cleo = Member.objects.create(name="Cleo")

        Progress.objects.create(book=cls.book, member=cls.ada, pages_read=440)
        Progress.objects.create(book=cls.book, member=cls.bob, pages_read=880)

    def _names(self, response):
        return [row["member"].name for row in response.context["rows"]]

    def test_the_page_names_the_book_and_everyone_reading_it(self):
        response = self.client.get(reverse("club:progress"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Middlemarch")
        for name in ("Ada", "Bob", "Cleo"):
            self.assertContains(response, name)

    def test_members_are_ordered_furthest_along_first(self):
        response = self.client.get(reverse("club:progress"))

        self.assertEqual(self._names(response), ["Bob", "Ada", "Cleo"])

    def test_a_member_with_nothing_recorded_still_appears_with_no_number(self):
        """Omitting them would make the table quietly wrong about who is
        behind — the person who has not started is exactly who it is about."""
        response = self.client.get(reverse("club:progress"))

        cleo = response.context["rows"][-1]
        self.assertEqual(cleo["member"], self.cleo)
        self.assertIsNone(cleo["units_read"])
        self.assertIsNone(cleo["percent"])
        self.assertIs(cleo["has_recorded"], False)
        self.assertContains(response, "not started")

    def test_a_recorded_zero_reads_differently_from_nothing_recorded(self):
        Progress.objects.create(book=self.book, member=self.cleo, pages_read=0)

        response = self.client.get(reverse("club:progress"))

        cleo = response.context["rows"][-1]
        self.assertEqual(cleo["units_read"], 0)
        self.assertIs(cleo["has_recorded"], True)
        self.assertNotContains(response, "not started")

    def test_a_deactivated_member_is_left_out_entirely(self):
        """Decision #3 keeps them on the roster page, marked. Here they would
        be permanently last and permanently behind, which is not true of
        somebody who has left."""
        self.cleo.is_active = False
        self.cleo.save(update_fields=["is_active"])

        response = self.client.get(reverse("club:progress"))

        self.assertEqual(self._names(response), ["Bob", "Ada"])
        self.assertNotContains(response, "Cleo")

    def test_a_deactivated_members_recorded_progress_goes_with_them(self):
        self.ada.is_active = False
        self.ada.save(update_fields=["is_active"])

        response = self.client.get(reverse("club:progress"))

        self.assertNotIn("Ada", self._names(response))
        self.assertTrue(Progress.objects.filter(member=self.ada).exists())

    def test_each_row_carries_its_number_as_text_beside_the_bar(self):
        """Design system: colour and length never carry the meaning alone."""
        response = self.client.get(reverse("club:progress"))

        self.assertContains(response, "440 of 880")
        self.assertContains(response, "50%")
        self.assertContains(response, "100%")
        self.assertContains(response, 'style="width: 50%"')

    def test_the_bar_is_hidden_from_assistive_technology(self):
        """It repeats the number next to it and has nothing of its own."""
        response = self.client.get(reverse("club:progress"))

        self.assertContains(response, '<span class="progress" aria-hidden="true">')

    def test_progress_on_another_book_does_not_leak_in(self):
        other = Book.objects.create(title="Piranesi", author="Susanna Clarke")
        Progress.objects.create(book=other, member=self.cleo, pages_read=200)

        response = self.client.get(reverse("club:progress"))

        cleo = response.context["rows"][-1]
        self.assertEqual(cleo["member"], self.cleo)
        self.assertIsNone(cleo["units_read"])


class ProgressOverviewQueryCountTests(TestCase):
    """The N+1 the table would grow into if a row asked for its own progress."""

    @classmethod
    def setUpTestData(cls):
        cls.book = Book.objects.create(
            title="Middlemarch", author="George Eliot", total_pages=880, is_current=True
        )

    def _add_members(self, count, pages=100):
        start = Member.objects.count()
        for index in range(start, start + count):
            member = Member.objects.create(name=f"Member {index:02d}")
            # Through `record()`, so the log has something in it. The pin below
            # is what says the overview never reads it, and a link per row
            # never becomes a query per row (#18).
            Progress(book=self.book, member=member, pages_read=pages).record()

    def test_the_query_count_does_not_grow_with_the_roster(self):
        self._add_members(2)
        with self.assertNumQueries(2):
            self.client.get(reverse("club:progress"))

        self._add_members(20)
        with self.assertNumQueries(2):
            self.client.get(reverse("club:progress"))

    def test_the_two_queries_are_the_book_and_the_roster(self):
        """Pinned so that the number above is a fact about this page rather
        than whatever it happened to be on the day it was written."""
        self._add_members(3)

        with self.assertNumQueries(2):
            response = self.client.get(reverse("club:progress"))

        self.assertEqual(len(response.context["rows"]), 3)


class ProgressOverviewNoPageCountTests(TestCase):
    """A book nobody has looked up the page count for."""

    @classmethod
    def setUpTestData(cls):
        cls.book = Book.objects.create(
            title="Untitled", author="A", is_current=True
        )
        cls.ada = Member.objects.create(name="Ada")
        Progress.objects.create(book=cls.book, member=cls.ada, pages_read=120)

    def test_the_page_shows_pages_and_says_why_there_is_no_percentage(self):
        response = self.client.get(reverse("club:progress"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "120")
        self.assertContains(response, "no page or chapter count recorded")
        self.assertIsNone(response.context["rows"][0]["percent"])

    def test_no_bar_is_drawn_at_all(self):
        """A bar with no percentage behind it would be a decorative zero."""
        response = self.client.get(reverse("club:progress"))

        self.assertNotContains(response, "progress__fill")


class ProgressOverviewInChaptersTests(TestCase):
    """The same table, on a book measured in chapters (#17)."""

    @classmethod
    def setUpTestData(cls):
        cls.book = Book.objects.create(
            title="Piranesi",
            author="Susanna Clarke",
            total_chapters=30,
            started_on=date(2025, 9, 1),
            is_current=True,
        )
        cls.ada = Member.objects.create(name="Ada")
        cls.bob = Member.objects.create(name="Bob")
        cls.cleo = Member.objects.create(name="Cleo")

        Progress.objects.create(book=cls.book, member=cls.ada, chapters_read=12)
        Progress.objects.create(book=cls.book, member=cls.bob, chapters_read=30)

    def _names(self, response):
        return [row["member"].name for row in response.context["rows"]]

    def test_each_count_names_its_unit_rather_than_standing_bare(self):
        response = self.client.get(reverse("club:progress"))

        self.assertContains(response, "12 of 30 chapters")
        self.assertContains(response, "40%")
        self.assertNotContains(response, "pages")

    def test_the_byline_names_the_chapter_count(self):
        response = self.client.get(reverse("club:progress"))

        self.assertContains(response, "30 chapters")

    def test_members_are_ordered_furthest_along_first(self):
        response = self.client.get(reverse("club:progress"))

        self.assertEqual(self._names(response), ["Bob", "Ada", "Cleo"])

    def test_the_percentage_is_derived_from_the_chapter_count(self):
        response = self.client.get(reverse("club:progress"))

        rows = {row["member"].name: row for row in response.context["rows"]}
        self.assertEqual(rows["Ada"]["percent"], 40)
        self.assertEqual(rows["Bob"]["percent"], 100)

    def test_a_member_with_nothing_recorded_is_not_started(self):
        response = self.client.get(reverse("club:progress"))

        cleo = response.context["rows"][-1]
        self.assertIs(cleo["has_recorded"], False)
        self.assertContains(response, "not started")

    def test_a_recorded_zero_still_reads_differently_from_nothing_recorded(self):
        """Decision #19, on the new column: nought chapters is a sentence."""
        Progress.objects.create(book=self.book, member=self.cleo, chapters_read=0)

        response = self.client.get(reverse("club:progress"))

        cleo = response.context["rows"][-1]
        self.assertIs(cleo["has_recorded"], True)
        self.assertContains(response, "0 of 30 chapters")
        self.assertNotContains(response, "not started")

    def test_a_book_nobody_has_recorded_against_shows_the_roster_not_zeroes(self):
        Progress.objects.filter(book=self.book).delete()

        response = self.client.get(reverse("club:progress"))

        self.assertEqual(len(response.context["rows"]), 3)
        self.assertNotContains(response, "of 30 chapters")
        for row in response.context["rows"]:
            with self.subTest(member=row["member"].name):
                self.assertIs(row["has_recorded"], False)


class ProgressOverviewMeasureChangeTests(TestCase):
    """The book that drops its page count and gains a chapter count."""

    @classmethod
    def setUpTestData(cls):
        cls.book = Book.objects.create(
            title="Middlemarch",
            author="George Eliot",
            total_pages=880,
            is_current=True,
        )
        cls.ada = Member.objects.create(name="Ada")
        cls.bob = Member.objects.create(name="Bob")
        Progress.objects.create(book=cls.book, member=cls.ada, pages_read=431)

    def _switch_to_chapters(self):
        self.book.total_pages = None
        self.book.total_chapters = 30
        self.book.save(update_fields=["total_pages", "total_chapters"])

    def test_the_member_reads_as_not_started_rather_than_431_of_30(self):
        """Nor 0 of 30: decision #19 says a recorded zero is a member saying
        something, and this member has said nothing about chapters."""
        self._switch_to_chapters()

        response = self.client.get(reverse("club:progress"))

        ada = {row["member"].name: row for row in response.context["rows"]}["Ada"]
        self.assertIs(ada["has_recorded"], False)
        self.assertNotContains(response, "431")
        self.assertNotContains(response, "0 of 30")
        self.assertContains(response, "not started")

    def test_the_page_count_is_still_in_the_database(self):
        self._switch_to_chapters()

        self.client.get(reverse("club:progress"))

        self.assertEqual(Progress.objects.get(member=self.ada).pages_read, 431)

    def test_re_recording_in_chapters_puts_the_member_back_on_the_table(self):
        self._switch_to_chapters()
        Progress.objects.filter(member=self.ada).update(chapters_read=6)

        response = self.client.get(reverse("club:progress"))

        ada = {row["member"].name: row for row in response.context["rows"]}["Ada"]
        self.assertIs(ada["has_recorded"], True)
        self.assertEqual(ada["units_read"], 6)
        self.assertEqual(ada["percent"], 20)


class ProgressOverviewChapterQueryCountTests(TestCase):
    """The subquery picks a column; it does not become a second query."""

    @classmethod
    def setUpTestData(cls):
        cls.book = Book.objects.create(
            title="Piranesi",
            author="Susanna Clarke",
            total_chapters=30,
            is_current=True,
        )

    def _add_members(self, count, chapters=4):
        start = Member.objects.count()
        for index in range(start, start + count):
            member = Member.objects.create(name=f"Member {index:02d}")
            # Recorded through `record()`, so every row carries a log entry the
            # overview must still not go looking for (#18).
            Progress(
                book=self.book, member=member, chapters_read=chapters
            ).record()

    def test_the_query_count_does_not_grow_with_the_roster(self):
        self._add_members(2)
        with self.assertNumQueries(2):
            self.client.get(reverse("club:progress"))

        self._add_members(20)
        with self.assertNumQueries(2):
            response = self.client.get(reverse("club:progress"))

        self.assertEqual(len(response.context["rows"]), 22)


class ProgressOverviewNeitherCountTests(TestCase):
    """A book with no page count and no chapter count either."""

    @classmethod
    def setUpTestData(cls):
        cls.book = Book.objects.create(title="Untitled", author="A", is_current=True)
        cls.ada = Member.objects.create(name="Ada")
        Progress.objects.create(book=cls.book, member=cls.ada, pages_read=120)

    def test_the_empty_state_names_both_counts(self):
        response = self.client.get(reverse("club:progress"))

        self.assertContains(response, "no page or chapter count recorded")

    def test_the_count_is_still_shown_with_its_unit(self):
        response = self.client.get(reverse("club:progress"))

        self.assertContains(response, "120 pages")


class ProgressOverviewEmptyStatesTests(TestCase):
    """Both of the ways this page can have nothing to show."""

    def test_no_current_book_says_so(self):
        Member.objects.create(name="Ada")

        response = self.client.get(reverse("club:progress"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No book in progress — an admin can start one.")

    def test_no_members_says_so(self):
        Book.objects.create(title="Middlemarch", author="George Eliot", is_current=True)

        response = self.client.get(reverse("club:progress"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nobody is on the roster yet")

    def test_only_deactivated_members_is_the_same_as_none(self):
        Book.objects.create(title="Middlemarch", author="George Eliot", is_current=True)
        Member.objects.create(name="Ada", is_active=False)

        response = self.client.get(reverse("club:progress"))

        self.assertContains(response, "Nobody is on the roster yet")

    def test_neither_a_book_nor_members_still_renders(self):
        response = self.client.get(reverse("club:progress"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No book in progress")


class ProgressOverviewLinksTests(TestCase):
    """Getting from looking at the table to being in it."""

    @classmethod
    def setUpTestData(cls):
        cls.book = Book.objects.create(
            title="Middlemarch", author="George Eliot", total_pages=880, is_current=True
        )
        cls.ada = Member.objects.create(name="Ada")

    def test_each_row_links_to_that_members_trail_through_this_book(self):
        """#18. Through `{% url %}`, and off objects the page already has."""
        response = self.client.get(reverse("club:progress"))

        self.assertContains(
            response,
            reverse("club:progress_trail", args=[self.book.pk, self.ada.pk]),
        )

    def test_the_nav_reaches_the_overview(self):
        response = self.client.get(reverse("club:home"))

        self.assertContains(response, reverse("club:progress"))

    def test_an_identified_member_is_offered_the_update_form(self):
        session = self.client.session
        session["member_id"] = self.ada.pk
        session.save()

        response = self.client.get(reverse("club:progress"))

        self.assertContains(response, reverse("club:progress_update"))

    def test_a_stranger_is_asked_who_they_are_first(self):
        """Sending them straight to the form would work — the gate redirects
        them here anyway — but saying so up front is one fewer surprise."""
        response = self.client.get(reverse("club:progress"))

        self.assertContains(response, "Say who you are")
        self.assertNotContains(response, reverse("club:progress_update"))


class ProgressOverviewInMinutesTests(TestCase):
    """An audiobook: time listened, shown as time (decision #34)."""

    @classmethod
    def setUpTestData(cls):
        cls.book = Book.objects.create(
            title="Piranesi",
            author="Susanna Clarke",
            total_minutes=750,
            is_current=True,
        )
        cls.ada = Member.objects.create(name="Ada")
        cls.bob = Member.objects.create(name="Bob")
        cls.cleo = Member.objects.create(name="Cleo")
        cls.dev = Member.objects.create(name="Dev")

        Progress.objects.create(book=cls.book, member=cls.ada, minutes_read=252)
        Progress.objects.create(book=cls.book, member=cls.bob, minutes_read=0)
        # A row from before the book was measured in time: pages only.
        Progress.objects.create(book=cls.book, member=cls.cleo, pages_read=431)

    def _get(self):
        return self.client.get(reverse("club:progress"))

    def test_progress_and_total_are_shown_as_time(self):
        response = self._get()

        self.assertContains(response, "4h 12m of 12h 30m")
        self.assertContains(response, "34%")
        self.assertContains(response, "12h 30m")
        self.assertNotContains(response, "252")
        self.assertNotContains(response, "750")

    def test_a_recorded_zero_is_shown_as_zero_minutes_and_zero_percent(self):
        response = self._get()

        self.assertContains(response, "0m of 12h 30m")
        self.assertContains(response, "0%")

    def test_ordering_puts_furthest_along_first_and_unrecorded_last(self):
        names = [row["member"].name for row in self._get().context["rows"]]

        self.assertEqual(names, ["Ada", "Bob", "Cleo", "Dev"])

    def test_a_pages_only_legacy_row_reads_as_not_started(self):
        rows = {row["member"].name: row for row in self._get().context["rows"]}

        self.assertIs(rows["Cleo"]["has_recorded"], False)
        self.assertIs(rows["Dev"]["has_recorded"], False)
        self.assertIs(rows["Bob"]["has_recorded"], True)
        self.assertContains(self._get(), "not started")

    def test_nobody_who_has_recorded_nothing_shows_zero_minutes(self):
        html = self._get().content.decode()
        cleo_row = html.split("Cleo")[1].split("</tr>")[0]

        self.assertIn("not started", cleo_row)
        self.assertNotIn("0m", cleo_row)


class ProgressOverviewInMinutesQueryCountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.book = Book.objects.create(
            title="Piranesi",
            author="Susanna Clarke",
            total_minutes=750,
            is_current=True,
        )

    def _add_members(self, count):
        start = Member.objects.count()
        for index in range(start, start + count):
            member = Member.objects.create(name=f"Member {index:02d}")
            Progress(book=self.book, member=member, minutes_read=60).record()

    def test_the_query_count_does_not_grow_with_the_roster(self):
        self._add_members(2)
        with self.assertNumQueries(2):
            self.client.get(reverse("club:progress"))

        self._add_members(20)
        with self.assertNumQueries(2):
            response = self.client.get(reverse("club:progress"))

        self.assertEqual(len(response.context["rows"]), 22)


class ProgressOverviewNotStartedCellTests(TestCase):
    """#30: nothing recorded draws no "0%" and no bar; a recorded zero does.

    One page per measure, with a member who has not started, one who recorded
    a zero, and one part-way, so the three rows are compared side by side.
    """

    CASES = [
        ("pages", {"total_pages": 880}, "pages_read", "0 of 880 pages", 440),
        ("chapters", {"total_chapters": 30}, "chapters_read", "0 of 30 chapters", 15),
        ("minutes", {"total_minutes": 750}, "minutes_read", "0m of 12h 30m", 375),
    ]

    def _cells(self, response, name):
        html = response.content.decode()
        row = next(
            r for r in re.findall(r"<tr>.*?</tr>", html, re.S) if ">%s</a>" % name in r
        )
        tds = re.findall(r"<td>(.*?)</td>", row, re.S)
        return tds

    def test_not_started_has_no_percent_and_no_bar_on_every_measure(self):
        for label, total, column, zero_text, part in self.CASES:
            with self.subTest(measure=label):
                Book.objects.all().delete()
                Member.objects.all().delete()
                book = Book.objects.create(
                    title="B", author="A", is_current=True, **total
                )
                ada = Member.objects.create(name="Ada")
                bob = Member.objects.create(name="Bob")
                Member.objects.create(name="Cleo")
                Progress.objects.create(book=book, member=ada, **{column: part})
                Progress.objects.create(book=book, member=bob, **{column: 0})

                response = self.client.get(reverse("club:progress"))
                rows = {r["member"].name: r for r in response.context["rows"]}

                self.assertIsNone(rows["Cleo"]["units_read"])
                self.assertIsNone(rows["Cleo"]["percent"])
                self.assertEqual(rows["Bob"]["units_read"], 0)
                self.assertEqual(rows["Bob"]["percent"], 0)
                self.assertEqual(
                    [r["member"].name for r in response.context["rows"]],
                    ["Ada", "Bob", "Cleo"],
                )

                cleo_count, cleo_pct, _movement = self._cells(response, "Cleo")
                self.assertIn("not started", cleo_count)
                self.assertNotIn("0%", cleo_pct)
                self.assertNotIn("progress__fill", cleo_pct)
                self.assertNotIn('class="progress"', cleo_pct)
                self.assertTrue(cleo_pct.strip())
                self.assertIn('class="empty"', cleo_pct)

                bob_count, bob_pct, _movement = self._cells(response, "Bob")
                self.assertIn(zero_text, bob_count)
                self.assertIn("0%", bob_pct)
                self.assertIn("width: 0%", bob_pct)

                ada_count, ada_pct, _movement = self._cells(response, "Ada")
                self.assertIn("50%", ada_pct)
                self.assertIn('aria-hidden="true"', ada_pct)


class PagesReadNullOverviewTests(TestCase):
    """#29: a row recorded in another unit reads as not started on a page book."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.bob = Member.objects.create(name="Bob")
        cls.cleo = Member.objects.create(name="Cleo")

    def _book(self, **totals):
        return Book.objects.create(
            title="Middlemarch", author="George Eliot", is_current=True, **totals
        )

    def test_chapters_to_pages_reads_as_not_started(self):
        book = self._book(total_chapters=30)
        Progress.objects.create(book=book, member=self.ada, chapters_read=12)
        Book.objects.filter(pk=book.pk).update(total_chapters=None, total_pages=400)

        response = self.client.get(reverse("club:progress"))

        ada = response.context["rows"][0]
        self.assertIs(ada["has_recorded"], False)
        self.assertContains(response, "not started")
        self.assertNotContains(response, "0 of 400")

    def test_minutes_to_pages_reads_as_not_started(self):
        book = self._book(total_minutes=600)
        Progress.objects.create(book=book, member=self.ada, minutes_read=90)
        Book.objects.filter(pk=book.pk).update(total_minutes=None, total_pages=400)

        response = self.client.get(reverse("club:progress"))

        self.assertIs(response.context["rows"][0]["has_recorded"], False)
        self.assertNotContains(response, "0 of 400")

    def test_a_recorded_page_zero_reads_zero_of_the_total(self):
        book = self._book(total_pages=400)
        Progress.objects.create(book=book, member=self.ada, pages_read=0)

        response = self.client.get(reverse("club:progress"))

        self.assertIs(response.context["rows"][0]["has_recorded"], True)
        self.assertContains(response, "0 of 400")

    def test_null_pages_sort_after_a_recorded_zero(self):
        book = self._book(total_pages=400)
        Progress.objects.create(book=book, member=self.ada, chapters_read=5)
        Progress.objects.create(book=book, member=self.bob, pages_read=0)
        Progress.objects.create(book=book, member=self.cleo, pages_read=10)

        response = self.client.get(reverse("club:progress"))
        names = [row["member"].name for row in response.context["rows"]]

        self.assertEqual(names, ["Cleo", "Bob", "Ada"])

    def test_model_ordering_puts_null_pages_last(self):
        book = self._book(total_pages=400)
        Progress.objects.create(book=book, member=self.ada, chapters_read=5)
        Progress.objects.create(book=book, member=self.bob, pages_read=0)

        members = [p.member.name for p in Progress.objects.select_related("member")]

        self.assertEqual(members, ["Bob", "Ada"])


class ProgressOverviewMovementTests(TestCase):
    """The "This week" cell (#32): the current count minus a baseline.

    `recorded_on` is `auto_now_add`, so every entry is back-dated with
    `.update()`. Offsets are whole days and never within a day of the 7-day
    boundary, so a coarse clock tick cannot tie.
    """

    def setUp(self):
        self.book = Book.objects.create(
            title="Middlemarch", author="George Eliot", total_pages=100, is_current=True
        )
        self.ada = Member.objects.create(name="Ada")

    def _trail(self, member, *steps, book=None):
        """Record (days_ago, count) steps oldest first; the last is current."""
        book = book or self.book
        column = book.unit_column
        progress = Progress.objects.create(
            book=book, member=member, **{column: steps[-1][1]}
        )
        for days_ago, count in steps:
            entry = ProgressEntry.objects.create(progress=progress, **{column: count})
            ProgressEntry.objects.filter(pk=entry.pk).update(
                recorded_on=timezone.now() - timedelta(days=days_ago)
            )
        return progress

    def _row(self, name="Ada"):
        response = self.client.get(reverse("club:progress"))
        self.response = response
        return {r["member"].name: r for r in response.context["rows"]}[name]

    def _switch_book(self, **fields):
        Book.objects.filter(pk=self.book.pk).update(is_current=False)
        return Book.objects.create(is_current=True, **fields)

    def test_a_climb_from_20_to_60_percent_reads_as_plus_40_pages_and_percent(self):
        self._trail(self.ada, (10, 20), (2, 60))

        self._row()

        self.assertContains(self.response, "+40 pages, +40%")
        self.assertContains(self.response, "This week")

    def test_chapters_are_counted_in_chapters(self):
        book = self._switch_book(title="Piranesi", author="S", total_chapters=30)
        self._trail(self.ada, (10, 6), (2, 12), book=book)

        self._row()

        self.assertContains(self.response, "+6 chapters, +20%")

    def test_minutes_go_through_format_minutes_and_the_raw_count_is_hidden(self):
        book = self._switch_book(title="Audio", author="A", total_minutes=600)
        self._trail(self.ada, (10, 100), (2, 165), book=book)

        self._row()

        self.assertContains(self.response, "+1h 5m, +11%")
        self.assertNotContains(self.response, "+65")

    def test_a_decrease_keeps_its_minus(self):
        self._trail(self.ada, (10, 60), (2, 30))

        self._row()

        self.assertContains(self.response, "-30 pages, -30%")

    def test_the_baseline_is_the_newest_entry_at_or_before_the_window_start(self):
        self._trail(self.ada, (20, 5), (9, 30), (3, 50), (1, 70))

        self._row()

        self.assertContains(self.response, "+40 pages, +40%")

    def test_with_nothing_before_the_window_the_oldest_in_window_entry_is_the_baseline(self):
        self._trail(self.ada, (5, 10), (3, 25), (1, 40))

        self._row()

        self.assertContains(self.response, "+30 pages, +30%")

    def test_entries_all_before_the_window_read_as_no_change_this_week(self):
        self._trail(self.ada, (20, 10), (12, 40))

        self._row()

        self.assertContains(self.response, "no change this week")
        self.assertNotContains(self.response, "+0")

    def test_a_climb_and_a_return_inside_the_window_is_no_change(self):
        self._trail(self.ada, (10, 40), (3, 60), (1, 40))

        self._row()

        self.assertContains(self.response, "no change this week")

    def test_a_single_entry_inside_the_window_is_a_first_entry_with_no_delta(self):
        self._trail(self.ada, (2, 25))

        self._row()

        self.assertContains(self.response, "first entry this week")
        self.assertNotContains(self.response, "+25")

    def test_a_single_entry_before_the_window_is_no_change_not_first_entry(self):
        self._trail(self.ada, (12, 25))

        self._row()

        self.assertContains(self.response, "no change this week")
        self.assertNotContains(self.response, "first entry")

    def test_nothing_recorded_shows_no_movement_and_keeps_no_progress_yet(self):
        row = self._row()

        self.assertIs(row["has_recorded"], False)
        self.assertIsNone(row["movement"])
        self.assertContains(self.response, "no progress yet")
        self.assertNotContains(self.response, "no change this week")
        self.assertNotContains(self.response, "first entry")
        self.assertNotContains(self.response, "progress__fill")

    def test_a_recorded_zero_with_no_change_reads_no_change_this_week(self):
        self._trail(self.ada, (10, 0))

        self._row()

        self.assertContains(self.response, "no change this week")

    def test_entries_in_the_old_unit_alone_show_no_movement(self):
        progress = self._trail(self.ada, (10, 20), (2, 60))
        Book.objects.filter(pk=self.book.pk).update(total_pages=None, total_chapters=30)

        row = self._row()

        self.assertIs(row["has_recorded"], False)
        self.assertIsNone(row["movement"])
        self.assertNotContains(self.response, "+40")
        self.assertTrue(progress.entries.exists())

    def test_old_unit_entries_are_ignored_when_new_unit_entries_exist(self):
        progress = self._trail(self.ada, (10, 20), (2, 60))
        Book.objects.filter(pk=self.book.pk).update(total_pages=None, total_chapters=30)
        for days_ago, count in ((9, 3), (1, 9)):
            entry = ProgressEntry.objects.create(progress=progress, chapters_read=count)
            ProgressEntry.objects.filter(pk=entry.pk).update(
                recorded_on=timezone.now() - timedelta(days=days_ago)
            )
        Progress.objects.filter(pk=progress.pk).update(chapters_read=9)

        self._row()

        self.assertContains(self.response, "+6 chapters, +20%")
        self.assertNotContains(self.response, "+40")

    def test_a_book_with_no_total_shows_the_count_movement_without_a_percentage(self):
        Book.objects.filter(pk=self.book.pk).update(total_pages=None)
        self._trail(self.ada, (10, 20), (2, 60))

        self._row()

        self.assertContains(self.response, "+40 pages")
        self.assertNotContains(self.response, "%")

    def test_row_order_is_unchanged_by_movement(self):
        bob = Member.objects.create(name="Bob")
        Member.objects.create(name="Cleo")
        self._trail(self.ada, (10, 10), (2, 20))
        self._trail(bob, (10, 70), (2, 50))

        response = self.client.get(reverse("club:progress"))

        names = [r["member"].name for r in response.context["rows"]]
        self.assertEqual(names, ["Bob", "Ada", "Cleo"])

    def test_another_members_entries_do_not_leak_into_the_baseline(self):
        bob = Member.objects.create(name="Bob")
        self._trail(bob, (10, 90), (2, 95))
        self._trail(self.ada, (10, 20), (2, 30))

        self._row()

        self.assertContains(self.response, "+10 pages, +10%")
        self.assertContains(self.response, "+5 pages, +5%")

    def test_no_current_book_has_no_movement_column(self):
        Book.objects.filter(pk=self.book.pk).update(is_current=False)

        response = self.client.get(reverse("club:progress"))

        self.assertContains(response, "No book in progress")
        self.assertNotContains(response, "This week")


class ProgressOverviewMovementQueryCountTests(TestCase):
    """Baselines come from subqueries in the roster query, not per row."""

    @classmethod
    def setUpTestData(cls):
        cls.book = Book.objects.create(
            title="Middlemarch", author="George Eliot", total_pages=880, is_current=True
        )

    def _add_members(self, count):
        start = Member.objects.count()
        for index in range(start, start + count):
            member = Member.objects.create(name=f"Member {index:02d}")
            progress = Progress.objects.create(
                book=self.book, member=member, pages_read=300 + index
            )
            for days_ago, pages in ((20, 50), (9, 100), (5, 150), (2, 300 + index)):
                entry = ProgressEntry.objects.create(progress=progress, pages_read=pages)
                ProgressEntry.objects.filter(pk=entry.pk).update(
                    recorded_on=timezone.now() - timedelta(days=days_ago)
                )

    def test_the_query_count_stays_two_at_two_and_at_twenty_two_members(self):
        self._add_members(2)
        with self.assertNumQueries(2):
            self.client.get(reverse("club:progress"))

        self._add_members(20)
        with self.assertNumQueries(2):
            response = self.client.get(reverse("club:progress"))

        self.assertEqual(len(response.context["rows"]), 22)
        self.assertContains(response, "pages, +")
