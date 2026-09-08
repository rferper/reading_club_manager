"""The shared layout, and the landing page that shows the current read."""

from datetime import date

from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse
from django.utils import formats

from ..models import Book


class HomePageTests(TestCase):
    """Smoke test proving the project, app, URLconf and templates are wired up."""

    def test_home_page_responds(self):
        response = self.client.get(reverse("club:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Reading Club Manager")


class BaseTemplateTests(TestCase):
    """The shared layout every page extends."""

    def test_home_page_extends_the_base_layout(self):
        response = self.client.get(reverse("club:home"))

        self.assertTemplateUsed(response, "club/base.html")
        self.assertContains(response, 'aria-label="Main"')

    def test_stylesheet_is_linked(self):
        response = self.client.get(reverse("club:home"))

        self.assertContains(response, "club/style.css")

    def test_nav_links_only_to_routes_that_exist(self):
        """A {% url %} for a route nobody has written raises NoReverseMatch,
        and because every page extends the base that breaks the whole site
        rather than one page. Later issues add a nav entry with their route."""
        response = self.client.get(reverse("club:home"))

        self.assertContains(response, reverse("club:home"))
        self.assertContains(response, reverse("club:member_list"))
        for absent in ("/progress/", "/questions/", "/history/"):
            self.assertNotContains(response, f'href="{absent}"')

    def test_messages_are_rendered(self):
        html = render_to_string("club/base.html", {"messages": ["Progress saved."]})

        self.assertIn("Progress saved.", html)


class CurrentBookPageTests(TestCase):
    """The site root, with a book on it."""

    @classmethod
    def setUpTestData(cls):
        cls.book = Book.objects.create(
            title="Middlemarch",
            author="George Eliot",
            total_pages=880,
            started_on=date(2025, 9, 1),
            is_current=True,
        )

    def test_the_root_shows_what_the_club_is_reading(self):
        response = self.client.get(reverse("club:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Middlemarch")
        self.assertContains(response, "George Eliot")
        self.assertContains(response, formats.date_format(self.book.started_on))

    def test_a_finished_book_is_not_the_one_on_the_root(self):
        """Only the flag decides. A book finished yesterday belongs to the
        archive, not to the landing page."""
        Book.objects.create(
            title="Piranesi", author="Susanna Clarke", finished_on=date(2025, 8, 1)
        )

        response = self.client.get(reverse("club:home"))

        self.assertContains(response, "Middlemarch")
        self.assertNotContains(response, "Piranesi")

    def test_a_book_with_no_start_date_recorded_says_so(self):
        self.book.started_on = None
        self.book.save(update_fields=["started_on"])

        response = self.client.get(reverse("club:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Middlemarch")
        self.assertContains(response, "No start date recorded")

    def test_the_placeholder_from_the_skeleton_is_gone(self):
        response = self.client.get(reverse("club:home"))

        self.assertNotContains(response, "The project is set up")


class NoCurrentBookTests(TestCase):
    """Between reads — a state the club sits in, not an error (decision #2)."""

    def test_the_root_names_what_is_missing_and_who_can_fix_it(self):
        response = self.client.get(reverse("club:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No book in progress — an admin can start one.")

    def test_an_archive_full_of_finished_books_is_still_no_current_book(self):
        Book.objects.create(
            title="Piranesi", author="Susanna Clarke", finished_on=date(2025, 8, 1)
        )

        response = self.client.get(reverse("club:home"))

        self.assertContains(response, "No book in progress")
        self.assertNotContains(response, "Piranesi")
