"""The group overview: who is ahead, who is behind, and who has not started."""

from datetime import date

from django.test import TestCase
from django.urls import reverse

from ..models import Book, Member, Progress


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

    def test_a_member_with_nothing_recorded_appears_at_zero(self):
        """Omitting them would make the table quietly wrong about who is
        behind — the person who has not started is exactly who it is about."""
        response = self.client.get(reverse("club:progress"))

        cleo = response.context["rows"][-1]
        self.assertEqual(cleo["member"], self.cleo)
        self.assertEqual(cleo["pages_read"], 0)
        self.assertEqual(cleo["percent"], 0)
        self.assertIs(cleo["has_recorded"], False)
        self.assertContains(response, "not started")

    def test_a_recorded_zero_reads_differently_from_nothing_recorded(self):
        Progress.objects.create(book=self.book, member=self.cleo, pages_read=0)

        response = self.client.get(reverse("club:progress"))

        cleo = response.context["rows"][-1]
        self.assertEqual(cleo["pages_read"], 0)
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
        self.assertEqual(cleo["pages_read"], 0)


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
            Progress.objects.create(book=self.book, member=member, pages_read=pages)

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
        self.assertContains(response, "no page count recorded")
        self.assertIsNone(response.context["rows"][0]["percent"])

    def test_no_bar_is_drawn_at_all(self):
        """A bar with no percentage behind it would be a decorative zero."""
        response = self.client.get(reverse("club:progress"))

        self.assertNotContains(response, "progress__fill")


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
