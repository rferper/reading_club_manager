"""The admin PIN: the form, the gate, and what refusal means."""

import datetime
from unittest import mock
from urllib.parse import urlencode

from django.contrib.auth.models import User
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from ..decorators import club_admin_required
from ..models import Member
from .helpers import enter_admin


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
        enter_admin(session)
        session.save()

        response = self.client.get(reverse("club:admin_pin"))

        self.assertRedirects(response, reverse("club:home"))

    def test_pin_page_honours_next_when_the_flag_is_already_set(self):
        session = self.client.session
        enter_admin(session)
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
        enter_admin(session)
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
                enter_admin(request.session)

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
        enter_admin(session)
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
        enter_admin(session)
        session.save()

        self.client.logout()

        self.assertNotIn("is_club_admin", self.client.session)


@override_settings(
    CLUB_ADMIN_PIN="1234", CLUB_ADMIN_IDLE_SECONDS=100, CLUB_ADMIN_MAX_SECONDS=1000
)
class AdminModeExpiryTests(TestCase):
    """Admin mode lapses on idle time or total age (decision #33).

    The clock is patched, never slept on. Offsets are distinct whole seconds,
    so a coarse Windows clock tick cannot make two moments tie.
    """

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")

    def setUp(self):
        self.base = timezone.now()

    def at(self, seconds):
        """Patch `timezone.now` to `base + seconds` for the with-block."""
        return mock.patch(
            "django.utils.timezone.now",
            return_value=self.base + datetime.timedelta(seconds=seconds),
        )

    def enter_admin_at(self, seconds):
        with self.at(seconds):
            response = self.client.post(reverse("club:admin_pin"), {"pin": "1234"})
        self.assertEqual(response.status_code, 302)

    def get_at(self, seconds, name="club:member_add"):
        with self.at(seconds):
            return self.client.get(reverse(name))

    def test_admin_page_works_inside_the_idle_window(self):
        self.enter_admin_at(0)

        self.assertEqual(self.get_at(90).status_code, 200)

    def test_idle_past_the_limit_redirects_an_admin_page_to_the_pin(self):
        self.enter_admin_at(0)

        response = self.get_at(101)

        query = urlencode({"next": reverse("club:member_add")})
        self.assertRedirects(
            response,
            reverse("club:admin_pin") + "?" + query,
            fetch_redirect_response=False,
        )

    def test_idle_expiry_removes_the_flag_and_both_timestamps(self):
        self.enter_admin_at(0)

        self.get_at(101, "club:home")

        session = self.client.session
        for key in (
            "is_club_admin",
            "club_admin_started_at",
            "club_admin_last_used_at",
        ):
            self.assertNotIn(key, session)

    def test_idle_expiry_makes_a_post_to_an_admin_route_a_403(self):
        self.enter_admin_at(0)

        with self.at(101):
            response = self.client.post(reverse("club:member_add"), {"name": "Bo"})

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Member.objects.filter(name="Bo").exists())

    def test_admin_links_disappear_once_expired(self):
        self.enter_admin_at(0)
        self.assertContains(self.get_at(50, "club:home"), reverse("club:admin_exit"))

        response = self.get_at(200, "club:home")

        self.assertNotContains(response, reverse("club:admin_exit"))
        self.assertIs(response.context["is_club_admin"], False)

    def test_activity_extends_the_idle_window(self):
        self.enter_admin_at(0)
        self.get_at(80, "club:home")
        self.get_at(160, "club:home")

        # 240 is far past 100 from the start, but only 80 after the last use.
        self.assertEqual(self.get_at(240).status_code, 200)

    def test_a_page_that_merely_shows_admin_links_counts_as_activity(self):
        self.enter_admin_at(0)
        self.get_at(90, "club:home")

        self.assertEqual(self.get_at(170).status_code, 200)

    def test_max_age_ends_admin_mode_despite_continuous_activity(self):
        self.enter_admin_at(0)
        for seconds in range(90, 1000, 90):
            self.assertEqual(self.get_at(seconds).status_code, 200)

        # Last use was at 900; 1010 is within idle range but past the max age.
        response = self.get_at(1010)

        self.assertEqual(response.status_code, 302)
        self.assertNotIn("is_club_admin", self.client.session)

    def test_expiry_leaves_the_identified_member_in_place(self):
        session = self.client.session
        session["member_id"] = self.ada.pk
        session.save()
        self.enter_admin_at(0)

        response = self.get_at(101, "club:home")

        self.assertEqual(self.client.session["member_id"], self.ada.pk)
        self.assertEqual(response.context["current_member"], self.ada)

    def test_a_flag_without_timestamps_is_treated_as_expired(self):
        session = self.client.session
        session["is_club_admin"] = True
        session.save()

        response = self.client.get(reverse("club:member_add"))

        self.assertEqual(response.status_code, 302)
        self.assertNotIn("is_club_admin", self.client.session)

    def test_a_flag_without_timestamps_cannot_post(self):
        session = self.client.session
        session["is_club_admin"] = True
        session.save()

        response = self.client.post(reverse("club:member_add"), {"name": "Bo"})

        self.assertEqual(response.status_code, 403)

    def test_expiry_adds_no_message(self):
        self.enter_admin_at(0)
        self.client.get(reverse("club:home"))  # drain the "Admin mode is on." message

        response = self.get_at(101, "club:home")

        self.assertEqual(list(response.context["messages"]), [])

    def test_exit_removes_the_flag_and_both_timestamps(self):
        self.enter_admin_at(0)

        with self.at(10):
            self.client.post(reverse("club:admin_exit"))

        session = self.client.session
        self.assertNotIn("is_club_admin", session)
        self.assertNotIn("club_admin_started_at", session)
        self.assertNotIn("club_admin_last_used_at", session)

    def test_correct_pin_stores_both_timestamps(self):
        self.enter_admin_at(7)

        session = self.client.session
        self.assertIn("club_admin_started_at", session)
        self.assertEqual(
            session["club_admin_started_at"], session["club_admin_last_used_at"]
        )


@override_settings(CLUB_ADMIN_PIN="1234")
class SessionKeyRotationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")

    def identified_session_key(self):
        session = self.client.session
        session["member_id"] = self.ada.pk
        session.save()
        return session.session_key

    def test_correct_pin_changes_the_session_key_and_keeps_the_member(self):
        before = self.identified_session_key()

        self.client.post(reverse("club:admin_pin"), {"pin": "1234"})

        after = self.client.session.session_key
        self.assertNotEqual(before, after)
        self.assertEqual(self.client.session["member_id"], self.ada.pk)

    def test_wrong_pin_does_not_rotate_the_session_key(self):
        before = self.identified_session_key()

        self.client.post(reverse("club:admin_pin"), {"pin": "9999"})

        self.assertEqual(self.client.session.session_key, before)
