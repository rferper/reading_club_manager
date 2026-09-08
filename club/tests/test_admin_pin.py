"""The admin PIN: the form, the gate, and what refusal means."""

from urllib.parse import urlencode

from django.contrib.auth.models import User
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from ..decorators import club_admin_required


@override_settings(CLUB_ADMIN_PIN="1234")
class AdminPinFormTests(TestCase):
    """Entering the PIN: the one door into admin mode."""

    def test_pin_page_renders_a_labelled_field(self):
        response = self.client.get(reverse("club:admin_pin"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Admin PIN")
        self.assertContains(response, 'type="password"')

    def test_correct_pin_sets_the_flag_and_lands_on_home(self):
        response = self.client.post(reverse("club:admin_pin"), {"pin": "1234"})

        self.assertRedirects(response, reverse("club:home"))
        self.assertIs(self.client.session["is_club_admin"], True)

    def test_correct_pin_returns_to_where_the_admin_came_from(self):
        response = self.client.post(
            reverse("club:admin_pin"), {"pin": "1234", "next": "/somewhere/"}
        )

        self.assertEqual(response["Location"], "/somewhere/")

    def test_wrong_pin_sets_nothing_and_says_so(self):
        response = self.client.post(reverse("club:admin_pin"), {"pin": "9999"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "That PIN is not right.")
        self.assertNotIn("is_club_admin", self.client.session)

    def test_a_failed_attempt_echoes_neither_pin_back_into_the_page(self):
        """`PasswordInput` drops the submitted value, and the configured PIN
        never reaches the template at all — only the boolean saying one is set."""
        response = self.client.post(reverse("club:admin_pin"), {"pin": "9999"})

        self.assertNotContains(response, "1234")
        self.assertNotContains(response, "9999")

    def test_pin_page_skips_the_form_once_the_flag_is_set(self):
        session = self.client.session
        session["is_club_admin"] = True
        session.save()

        response = self.client.get(reverse("club:admin_pin"))

        self.assertRedirects(response, reverse("club:home"))

    def test_pin_page_honours_next_when_the_flag_is_already_set(self):
        session = self.client.session
        session["is_club_admin"] = True
        session.save()

        response = self.client.get(reverse("club:admin_pin"), {"next": "/somewhere/"})

        self.assertEqual(response["Location"], "/somewhere/")


@override_settings(CLUB_ADMIN_PIN="")
class BlankPinFailsClosedTests(TestCase):
    """A blank PIN makes admin mode unreachable rather than open to everyone.

    `CLUB_ADMIN_PIN=` in the environment resolves to `""`, not to the `0000`
    default, so the check is on the resolved setting.
    """

    def test_the_page_says_admin_mode_is_unavailable(self):
        response = self.client.get(reverse("club:admin_pin"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "no PIN is configured")

    def test_an_empty_submission_does_not_open_admin_mode(self):
        self.client.post(reverse("club:admin_pin"), {"pin": ""})

        self.assertNotIn("is_club_admin", self.client.session)

    def test_a_non_empty_submission_does_not_open_admin_mode(self):
        self.client.post(reverse("club:admin_pin"), {"pin": "0000"})

        self.assertNotIn("is_club_admin", self.client.session)


@override_settings(CLUB_ADMIN_PIN="1234")
class AdminPinNextUrlTests(TestCase):
    """`?next=` is submitted data, so it is validated before it is trusted."""

    def test_a_next_pointing_off_site_falls_back_to_home(self):
        for hostile in ("https://evil.example/", "//evil.example/"):
            with self.subTest(next=hostile):
                response = self.client.post(
                    reverse("club:admin_pin"), {"pin": "1234", "next": hostile}
                )

                self.assertRedirects(response, reverse("club:home"))
                self.assertNotIn("evil.example", response["Location"])
                self.client.logout()

    def test_a_next_pointing_back_at_the_pin_pages_falls_back_to_home(self):
        """Otherwise a bookmarked `?next=/admin-pin/` bounces the PIN page off
        itself, and `?next=/admin-pin/exit/` walks straight back out again."""
        for loop in (reverse("club:admin_pin"), reverse("club:admin_exit")):
            with self.subTest(next=loop):
                response = self.client.post(
                    reverse("club:admin_pin"), {"pin": "1234", "next": loop}
                )

                self.assertRedirects(response, reverse("club:home"))
                self.client.logout()


@override_settings(CLUB_ADMIN_PIN="1234")
class AdminExitTests(TestCase):
    """Leaving admin mode is a state change, so it is a POST."""

    def setUp(self):
        session = self.client.session
        session["is_club_admin"] = True
        session.save()

    def test_post_clears_the_flag_and_says_so(self):
        response = self.client.post(reverse("club:admin_exit"), follow=True)

        self.assertRedirects(response, reverse("club:home"))
        self.assertNotIn("is_club_admin", self.client.session)
        self.assertContains(response, "Admin mode is off.")

    def test_a_get_is_refused_even_in_admin_mode(self):
        """`require_POST` is outermost, so the method is rejected before the
        session is consulted: no link can ever leave admin mode."""
        response = self.client.get(reverse("club:admin_exit"))

        self.assertEqual(response.status_code, 405)
        self.assertIs(self.client.session["is_club_admin"], True)

    def test_a_get_without_the_flag_is_also_a_405_not_a_redirect(self):
        session = self.client.session
        session.pop("is_club_admin")
        session.save()

        response = self.client.get(reverse("club:admin_exit"))

        self.assertEqual(response.status_code, 405)


class ClubAdminRequiredTests(TestCase):
    """The gate itself, exercised on a view that exists only here.

    It gets no route and no row in `_docs/api.md`, which is why this is the one
    place in the suite that types a path instead of reversing one.
    """

    def setUp(self):
        self.calls = []

        @club_admin_required
        def gated(request):
            self.calls.append(request)
            return HttpResponse("the admin-only body")

        self.gated = gated

    def _request(self, method, path="/gated/"):
        request = getattr(RequestFactory(), method)(path)
        SessionMiddleware(lambda r: None).process_request(request)
        return request

    def test_a_post_without_the_flag_is_a_403_and_the_view_never_runs(self):
        """A redirect would answer the POST with a GET and drop the payload,
        and an automated caller would read the 302 as success."""
        request = self._request("post")

        with self.assertRaises(PermissionDenied):
            self.gated(request)

        self.assertEqual(self.calls, [])

    def test_a_get_without_the_flag_redirects_carrying_where_it_came_from(self):
        request = self._request("get", "/gated/?page=2")

        response = self.gated(request)

        self.assertEqual(response.status_code, 302)
        query = urlencode({"next": "/gated/?page=2"})
        self.assertEqual(
            response["Location"], reverse("club:admin_pin") + "?" + query
        )
        self.assertEqual(self.calls, [])

    def test_the_flag_lets_the_view_run_on_any_method(self):
        for method in ("get", "post"):
            with self.subTest(method=method):
                request = self._request(method)
                request.session["is_club_admin"] = True

                response = self.gated(request)

                self.assertEqual(response.status_code, 200)
                self.assertIn(b"the admin-only body", response.content)


@override_settings(CLUB_ADMIN_PIN="1234")
class AdminModeIndicatorTests(TestCase):
    """What the header shows. Decoration — the decorator is the enforcement."""

    def test_a_visitor_without_the_flag_is_offered_the_way_in(self):
        response = self.client.get(reverse("club:home"))

        self.assertContains(response, "Enter admin mode")
        self.assertContains(response, reverse("club:admin_pin"))
        self.assertNotContains(response, reverse("club:admin_exit"))

    def test_an_admin_sees_the_indicator_and_a_post_form_to_leave(self):
        session = self.client.session
        session["is_club_admin"] = True
        session.save()

        response = self.client.get(reverse("club:home"))

        self.assertContains(response, "Admin mode")
        self.assertContains(response, reverse("club:admin_exit"))
        self.assertContains(response, "csrfmiddlewaretoken")

    def test_the_context_processor_is_false_rather_than_absent(self):
        response = self.client.get(reverse("club:home"))

        self.assertIs(response.context["is_club_admin"], False)


class AdminModeLifetimeTests(TestCase):
    """How long the flag lasts, and the one thing that ends it by surprise."""

    def test_logging_out_of_djangos_admin_clears_club_admin_mode(self):
        """`django.contrib.auth.logout()` flushes the whole session, and the
        flag lives in it. Accepted, not a bug — this test exists so the next
        person meets it in a test name rather than in the browser."""
        superuser = User.objects.create_superuser(
            username="root", email="root@example.com", password="not-a-real-password"
        )
        self.client.force_login(superuser)

        session = self.client.session
        session["is_club_admin"] = True
        session.save()

        self.client.logout()

        self.assertNotIn("is_club_admin", self.client.session)
