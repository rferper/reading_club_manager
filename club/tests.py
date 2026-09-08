from datetime import date
from urllib.parse import urlencode

from django.contrib.auth.models import User
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.exceptions import (
    NON_FIELD_ERRORS,
    PermissionDenied,
    ValidationError,
)
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import formats, timezone

from .decorators import club_admin_required
from .models import Member


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


class MemberModelTests(TestCase):
    """The roster row itself: defaults, string form and ordering."""

    def test_a_member_needs_only_a_name(self):
        member = Member.objects.create(name="Ada")

        self.assertEqual(member.role, "")
        self.assertIs(member.is_active, True)
        self.assertEqual(member.joined_on, timezone.localdate())

    def test_str_is_the_bare_name_even_when_deactivated(self):
        """__str__ renders beside old notes and answers, so a departed
        member's note still reads `Ada` and nothing else."""
        member = Member.objects.create(name="Ada", role="Founder", is_active=False)

        self.assertEqual(str(member), "Ada")

    def test_members_are_ordered_case_insensitively_by_name(self):
        zoe = Member.objects.create(name="Zoe")
        ada = Member.objects.create(name="ada")
        bob = Member.objects.create(name="Bob")

        self.assertEqual(list(Member.objects.all()), [ada, bob, zoe])

    def test_deactivated_members_keep_their_place_in_the_order(self):
        """is_active is not part of the sort: inactive members stay in name
        order and stay in the default queryset."""
        zoe = Member.objects.create(name="Zoe")
        ada = Member.objects.create(name="ada", is_active=False)
        bob = Member.objects.create(name="Bob")

        self.assertEqual(list(Member.objects.all()), [ada, bob, zoe])


class MemberNameUniquenessTests(TestCase):
    """A viewer picks their own name off this roster (decision #4), so two
    entries that differ only in capitalisation make that pick a coin toss."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")

    def test_duplicate_name_is_rejected(self):
        with self.assertRaises(ValidationError) as caught:
            Member(name="Ada").full_clean()

        self.assertIn("name", caught.exception.message_dict)

    def test_name_differing_only_in_case_is_rejected(self):
        with self.assertRaises(ValidationError) as caught:
            Member(name="ada").full_clean()

        self.assertIn(
            "A member with that name already exists.",
            caught.exception.message_dict[NON_FIELD_ERRORS],
        )

    def test_duplicate_name_is_rejected_by_the_database(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Member.objects.create(name="Ada")

    def test_case_only_duplicate_is_rejected_by_the_database(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Member.objects.create(name="ada")


class MemberAdminTests(TestCase):
    """The roster's only editing surface until #5 builds one in the app."""

    @classmethod
    def setUpTestData(cls):
        cls.superuser = User.objects.create_superuser(
            username="root", email="root@example.com", password="not-a-real-password"
        )
        cls.ada = Member.objects.create(name="Ada", role="Founder")

    def setUp(self):
        self.client.force_login(self.superuser)

    def test_superuser_can_add_and_deactivate_a_member(self):
        response = self.client.post(
            reverse("admin:club_member_add"),
            {
                "name": "Bob",
                "role": "Host",
                "is_active": "on",
                "joined_on": timezone.localdate().isoformat(),
            },
        )
        self.assertEqual(response.status_code, 302)
        bob = Member.objects.get(name="Bob")
        self.assertIs(bob.is_active, True)

        response = self.client.post(
            reverse("admin:club_member_change", args=[bob.pk]),
            {
                "name": "Bob",
                "role": "Host",
                "joined_on": bob.joined_on.isoformat(),
            },
        )
        self.assertEqual(response.status_code, 302)
        bob.refresh_from_db()
        self.assertIs(bob.is_active, False)

    def test_joined_on_can_be_backdated(self):
        """The field defaults to today but stays editable, so a founding
        member can be entered with the date they actually joined."""
        response = self.client.get(reverse("admin:club_member_add"))

        self.assertContains(response, timezone.localdate().isoformat())

        self.client.post(
            reverse("admin:club_member_add"),
            {
                "name": "Bob",
                "role": "",
                "is_active": "on",
                "joined_on": "2019-03-04",
            },
        )

        self.assertEqual(Member.objects.get(name="Bob").joined_on, date(2019, 3, 4))

    def test_members_cannot_be_deleted_through_the_admin(self):
        """Decision #3: members are deactivated, never deleted, and the
        default cascade would take their notes and answers with them."""
        delete_url = reverse("admin:club_member_delete", args=[self.ada.pk])

        self.assertEqual(self.client.get(delete_url).status_code, 403)
        self.assertEqual(self.client.post(delete_url, {"post": "yes"}).status_code, 403)
        self.assertTrue(Member.objects.filter(pk=self.ada.pk).exists())

        change_page = self.client.get(
            reverse("admin:club_member_change", args=[self.ada.pk])
        )
        self.assertNotContains(change_page, delete_url)

        changelist = self.client.get(reverse("admin:club_member_changelist"))
        self.assertNotContains(changelist, "delete_selected")

    def test_changelist_shows_the_roster_columns(self):
        response = self.client.get(reverse("admin:club_member_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            tuple(response.context["cl"].list_display),
            ("name", "role", "is_active", "joined_on"),
        )
        self.assertContains(response, "Founder")
        self.assertContains(response, formats.date_format(self.ada.joined_on))

    def test_changelist_is_filterable_and_searchable(self):
        zoe = Member.objects.create(name="Zoe", is_active=False)

        filtered = self.client.get(
            reverse("admin:club_member_changelist"), {"is_active__exact": "0"}
        )
        self.assertEqual(list(filtered.context["cl"].queryset), [zoe])

        searched = self.client.get(
            reverse("admin:club_member_changelist"), {"q": "Ada"}
        )
        self.assertEqual(list(searched.context["cl"].queryset), [self.ada])

    def test_changelist_keeps_the_case_insensitive_name_order(self):
        """ModelAdmin.ordering is deliberately unset, so the changelist
        inherits Meta.ordering instead of SQLite's binary collation."""
        zoe = Member.objects.create(name="Zoe")
        bob = Member.objects.create(name="bob")

        response = self.client.get(reverse("admin:club_member_changelist"))

        self.assertEqual(list(response.context["cl"].queryset), [self.ada, bob, zoe])


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
