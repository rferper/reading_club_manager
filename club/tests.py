from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse


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
        for absent in ("/members/", "/progress/", "/questions/", "/history/"):
            self.assertNotContains(response, f'href="{absent}"')

    def test_messages_are_rendered(self):
        html = render_to_string("club/base.html", {"messages": ["Progress saved."]})

        self.assertIn("Progress saved.", html)
