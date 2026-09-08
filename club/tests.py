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

from .decorators import club_admin_required, require_member
from .models import Book, Member


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


class MemberListTests(TestCase):
    """The roster page, which anyone may read."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada", role="Founder")
        cls.zoe = Member.objects.create(name="Zoe", is_active=False)

    def test_the_page_lists_every_member_with_their_role(self):
        response = self.client.get(reverse("club:member_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ada")
        self.assertContains(response, "Founder")

    def test_a_deactivated_member_is_marked_rather_than_hidden(self):
        """Decision #3: they left the club, not the record."""
        response = self.client.get(reverse("club:member_list"))

        self.assertContains(response, "Zoe")
        self.assertContains(response, "no longer reading with the club")

    def test_a_non_admin_sees_no_edit_controls(self):
        response = self.client.get(reverse("club:member_list"))

        self.assertNotContains(response, reverse("club:member_add"))
        self.assertNotContains(response, reverse("club:member_edit", args=[self.ada.pk]))
        self.assertNotContains(
            response, reverse("club:member_toggle", args=[self.ada.pk])
        )

    def test_an_admin_sees_them(self):
        session = self.client.session
        session["is_club_admin"] = True
        session.save()

        response = self.client.get(reverse("club:member_list"))

        self.assertContains(response, reverse("club:member_add"))
        self.assertContains(response, reverse("club:member_edit", args=[self.ada.pk]))
        self.assertContains(response, reverse("club:member_toggle", args=[self.ada.pk]))

    def test_the_nav_reaches_the_roster(self):
        response = self.client.get(reverse("club:home"))

        self.assertContains(response, reverse("club:member_list"))


class EmptyRosterTests(TestCase):
    """The state a fresh clone starts in, and the one templates break on."""

    def test_the_page_names_what_is_missing_and_who_can_fix_it(self):
        response = self.client.get(reverse("club:member_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nobody is on the roster yet")


class RosterGateTests(TestCase):
    """Hiding a control and enforcing a permission are different things.

    Every write route is driven here with no admin flag in the session, by the
    method it actually accepts, and asserted to change nothing.
    """

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada", role="Founder")

    def test_a_post_to_add_without_the_flag_is_refused(self):
        response = self.client.post(
            reverse("club:member_add"), {"name": "Mallory", "role": ""}
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Member.objects.filter(name="Mallory").exists())

    def test_a_post_to_edit_without_the_flag_is_refused(self):
        response = self.client.post(
            reverse("club:member_edit", args=[self.ada.pk]),
            {"name": "Mallory", "role": ""},
        )

        self.assertEqual(response.status_code, 403)
        self.ada.refresh_from_db()
        self.assertEqual(self.ada.name, "Ada")

    def test_a_post_to_toggle_without_the_flag_is_refused(self):
        response = self.client.post(reverse("club:member_toggle", args=[self.ada.pk]))

        self.assertEqual(response.status_code, 403)
        self.ada.refresh_from_db()
        self.assertIs(self.ada.is_active, True)

    def test_a_get_to_add_or_edit_without_the_flag_asks_for_the_pin(self):
        for url in (
            reverse("club:member_add"),
            reverse("club:member_edit", args=[self.ada.pk]),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertEqual(response.status_code, 302)
                self.assertTrue(
                    response["Location"].startswith(reverse("club:admin_pin"))
                )
                self.assertIn(urlencode({"next": url}), response["Location"])

    def test_toggle_refuses_a_get_even_from_an_admin(self):
        """`require_POST` is outermost, so nothing that changes the roster can
        hide behind a link somebody follows by accident."""
        session = self.client.session
        session["is_club_admin"] = True
        session.save()

        response = self.client.get(reverse("club:member_toggle", args=[self.ada.pk]))

        self.assertEqual(response.status_code, 405)
        self.ada.refresh_from_db()
        self.assertIs(self.ada.is_active, True)


class RosterAdminTests(TestCase):
    """What an admin can actually do from the browser, with no superuser."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada", role="Founder")

    def setUp(self):
        session = self.client.session
        session["is_club_admin"] = True
        session.save()

    def test_the_add_and_edit_pages_render_a_labelled_form(self):
        for url, heading in (
            (reverse("club:member_add"), "Add a member"),
            (reverse("club:member_edit", args=[self.ada.pk]), "Edit Ada"),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, heading)
                self.assertContains(response, 'for="id_name"')

    def test_an_admin_can_add_a_member(self):
        response = self.client.post(
            reverse("club:member_add"),
            {
                "name": "Bob",
                "role": "Host",
                "joined_on": timezone.localdate().isoformat(),
            },
            follow=True,
        )

        self.assertRedirects(response, reverse("club:member_list"))
        bob = Member.objects.get(name="Bob")
        self.assertEqual(bob.role, "Host")
        self.assertIs(bob.is_active, True)
        self.assertContains(response, "Bob is on the roster.")

    def test_a_founding_member_can_be_backdated(self):
        """Decision #13 keeps `joined_on` editable, and the goal of this page
        is a roster nobody needs a superuser account to maintain."""
        self.client.post(
            reverse("club:member_add"),
            {"name": "Bob", "role": "", "joined_on": "2019-03-04"},
        )

        self.assertEqual(Member.objects.get(name="Bob").joined_on, date(2019, 3, 4))

    def test_an_admin_can_rename_a_member_and_change_their_role(self):
        response = self.client.post(
            reverse("club:member_edit", args=[self.ada.pk]),
            {
                "name": "Ada Lovelace",
                "role": "Snack coordinator",
                "joined_on": self.ada.joined_on.isoformat(),
            },
        )

        self.assertRedirects(response, reverse("club:member_list"))
        self.ada.refresh_from_db()
        self.assertEqual(self.ada.name, "Ada Lovelace")
        self.assertEqual(self.ada.role, "Snack coordinator")

    def test_editing_a_member_does_not_collide_with_their_own_name(self):
        """The uniqueness check has to exclude the row being edited, or no
        member could ever have their role changed without being renamed."""
        response = self.client.post(
            reverse("club:member_edit", args=[self.ada.pk]),
            {
                "name": "Ada",
                "role": "Host",
                "joined_on": self.ada.joined_on.isoformat(),
            },
        )

        self.assertRedirects(response, reverse("club:member_list"))
        self.ada.refresh_from_db()
        self.assertEqual(self.ada.role, "Host")

    def test_toggling_deactivates_and_then_brings_a_member_back(self):
        url = reverse("club:member_toggle", args=[self.ada.pk])

        self.assertRedirects(self.client.post(url), reverse("club:member_list"))
        self.ada.refresh_from_db()
        self.assertIs(self.ada.is_active, False)

        self.assertRedirects(self.client.post(url), reverse("club:member_list"))
        self.ada.refresh_from_db()
        self.assertIs(self.ada.is_active, True)

    def test_toggling_a_member_who_is_not_there_is_a_404(self):
        response = self.client.post(reverse("club:member_toggle", args=[9999]))

        self.assertEqual(response.status_code, 404)


class RosterDuplicateNameTests(TestCase):
    """A duplicate name is a form error on the page, never a 500."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")

    def setUp(self):
        session = self.client.session
        session["is_club_admin"] = True
        session.save()

    def test_an_exact_duplicate_is_a_field_error(self):
        response = self.client.post(
            reverse("club:member_add"),
            {"name": "Ada", "role": "", "joined_on": "2024-01-01"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"], "name", "Member with this Name already exists."
        )
        self.assertEqual(Member.objects.count(), 1)

    def test_a_name_differing_only_in_case_is_a_form_error(self):
        """`unique=True` alone does not catch this — SQLite's default collation
        is case-sensitive. The `Lower("name")` constraint from decision #13 does,
        and it surfaces as a non-field error rather than an IntegrityError."""
        response = self.client.post(
            reverse("club:member_add"),
            {"name": "ada", "role": "", "joined_on": "2024-01-01"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            None,
            "A member with that name already exists.",
        )
        self.assertEqual(Member.objects.count(), 1)

    def test_renaming_a_member_onto_an_existing_name_is_a_form_error(self):
        bob = Member.objects.create(name="Bob")

        response = self.client.post(
            reverse("club:member_edit", args=[bob.pk]),
            {"name": "Ada", "role": "", "joined_on": bob.joined_on.isoformat()},
        )

        self.assertEqual(response.status_code, 200)
        bob.refresh_from_db()
        self.assertEqual(bob.name, "Bob")


class IdentifyPageTests(TestCase):
    """Picking your name off the roster, once per session."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.zoe = Member.objects.create(name="Zoe", is_active=False)

    def test_the_picker_lists_active_members_only(self):
        """A deactivated member is off the roster (decision #3), so picking
        them is not on offer — their old notes keep their name regardless."""
        response = self.client.get(reverse("club:identify"))

        self.assertEqual(response.status_code, 200)
        choices = list(response.context["form"].fields["member"].queryset)
        self.assertEqual(choices, [self.ada])
        self.assertContains(response, "Ada")
        self.assertNotContains(response, "Zoe")

    def test_picking_a_name_sticks_for_the_rest_of_the_session(self):
        response = self.client.post(
            reverse("club:identify"), {"member": self.ada.pk}, follow=True
        )

        self.assertRedirects(response, reverse("club:home"))
        self.assertEqual(self.client.session["member_id"], self.ada.pk)
        self.assertContains(response, "You are Ada.")

        later = self.client.get(reverse("club:member_list"))
        self.assertEqual(later.context["current_member"], self.ada)

    def test_picking_a_name_returns_the_viewer_where_they_came_from(self):
        response = self.client.post(
            reverse("club:identify"),
            {"member": self.ada.pk, "next": reverse("club:member_list")},
        )

        self.assertRedirects(response, reverse("club:member_list"))

    def test_a_deactivated_member_cannot_be_picked_by_id(self):
        """The dropdown does not offer Zoe; the form still has to refuse a
        hand-submitted id, because the list is not the enforcement."""
        response = self.client.post(reverse("club:identify"), {"member": self.zoe.pk})

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("member_id", self.client.session)

    def test_a_next_pointing_off_site_falls_back_to_home(self):
        for hostile in ("https://evil.example/", "//evil.example/"):
            with self.subTest(next=hostile):
                response = self.client.post(
                    reverse("club:identify"),
                    {"member": self.ada.pk, "next": hostile},
                )

                self.assertRedirects(response, reverse("club:home"))
                self.assertNotIn("evil.example", response["Location"])

    def test_a_next_pointing_back_at_the_picker_falls_back_to_home(self):
        for loop in (reverse("club:identify"), reverse("club:forget_me")):
            with self.subTest(next=loop):
                response = self.client.post(
                    reverse("club:identify"), {"member": self.ada.pk, "next": loop}
                )

                self.assertRedirects(response, reverse("club:home"))

    def test_switching_offers_the_current_name_as_the_starting_point(self):
        session = self.client.session
        session["member_id"] = self.ada.pk
        session.save()

        response = self.client.get(reverse("club:identify"))

        self.assertEqual(response.context["form"].initial["member"], self.ada)


class EmptyRosterIdentifyTests(TestCase):
    """Nobody to pick — the state a fresh clone starts in."""

    def test_the_picker_says_what_is_missing_instead_of_showing_a_blank_list(self):
        response = self.client.get(reverse("club:identify"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nobody is on the roster yet")
        self.assertNotContains(response, "That is me")


class ForgetMeTests(TestCase):
    """Clearing the session identity, which is a state change and so a POST."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")

    def setUp(self):
        session = self.client.session
        session["member_id"] = self.ada.pk
        session.save()

    def test_a_post_clears_the_identity(self):
        response = self.client.post(reverse("club:forget_me"), follow=True)

        self.assertRedirects(response, reverse("club:home"))
        self.assertNotIn("member_id", self.client.session)
        self.assertIsNone(response.context["current_member"])

    def test_a_get_is_refused(self):
        response = self.client.get(reverse("club:forget_me"))

        self.assertEqual(response.status_code, 405)
        self.assertEqual(self.client.session["member_id"], self.ada.pk)

    def test_forgetting_when_nobody_was_identified_is_not_an_error(self):
        self.client.post(reverse("club:forget_me"))

        response = self.client.post(reverse("club:forget_me"))

        self.assertRedirects(response, reverse("club:home"))


class StaleIdentityTests(TestCase):
    """A session pointing at a member who is no longer pickable.

    Sessions last two weeks (decision #14) and rosters change inside that, so
    this is ordinary, not exotic. It must clear itself rather than raise.
    """

    def test_a_session_naming_a_deactivated_member_clears_itself(self):
        ada = Member.objects.create(name="Ada")
        session = self.client.session
        session["member_id"] = ada.pk
        session.save()

        ada.is_active = False
        ada.save(update_fields=["is_active"])

        response = self.client.get(reverse("club:home"))

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["current_member"])
        self.assertNotIn("member_id", self.client.session)

    def test_a_session_naming_a_deleted_member_clears_itself(self):
        """Nothing in the app deletes a member — decision #3 — but a stale id
        from a rebuilt database has exactly this shape."""
        ada = Member.objects.create(name="Ada")
        session = self.client.session
        session["member_id"] = ada.pk
        session.save()
        ada.delete()

        response = self.client.get(reverse("club:home"))

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["current_member"])
        self.assertNotIn("member_id", self.client.session)

    def test_a_session_holding_nonsense_clears_itself(self):
        session = self.client.session
        session["member_id"] = 9999
        session.save()

        response = self.client.get(reverse("club:home"))

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["current_member"])


class IdentityIndicatorTests(TestCase):
    """The slot #2 left in the header."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")

    def test_an_unidentified_visitor_is_invited_to_say_who_they_are(self):
        response = self.client.get(reverse("club:home"))

        self.assertContains(response, "Who are you?")
        self.assertContains(response, reverse("club:identify"))

    def test_an_identified_viewer_sees_their_name_and_a_way_to_switch(self):
        session = self.client.session
        session["member_id"] = self.ada.pk
        session.save()

        response = self.client.get(reverse("club:home"))

        self.assertContains(response, "You are: Ada")
        self.assertContains(response, "switch")

    def test_the_context_entry_is_none_rather_than_absent(self):
        response = self.client.get(reverse("club:home"))

        self.assertIsNone(response.context["current_member"])

    def test_the_base_template_renders_without_a_request_at_all(self):
        """`render_to_string` runs no context processors, so both indicators
        must survive `current_member` and `is_club_admin` being undefined."""
        html = render_to_string("club/base.html", {})

        self.assertIn("Who are you?", html)


class RequireMemberTests(TestCase):
    """The identity gate, on a view that exists only here.

    Same refusal rule as the admin gate: the missing step on a safe method, a
    real refusal on anything that would have changed something.
    """

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")

    def setUp(self):
        self.calls = []

        @require_member
        def gated(request):
            self.calls.append(request)
            return HttpResponse("the members-only body")

        self.gated = gated

    def _request(self, method, path="/gated/"):
        request = getattr(RequestFactory(), method)(path)
        SessionMiddleware(lambda r: None).process_request(request)
        return request

    def test_a_get_from_a_stranger_asks_who_they_are_and_remembers_where(self):
        request = self._request("get", "/gated/?page=2")

        response = self.gated(request)

        self.assertEqual(response.status_code, 302)
        query = urlencode({"next": "/gated/?page=2"})
        self.assertEqual(
            response["Location"], reverse("club:identify") + "?" + query
        )
        self.assertEqual(self.calls, [])

    def test_a_post_from_a_stranger_is_a_403_and_the_view_never_runs(self):
        """A redirect would drop the payload, and `?next=` back to a POST-only
        route would land the viewer on a 405."""
        request = self._request("post")

        with self.assertRaises(PermissionDenied):
            self.gated(request)

        self.assertEqual(self.calls, [])

    def test_an_identified_member_gets_through(self):
        request = self._request("post")
        request.session["member_id"] = self.ada.pk

        response = self.gated(request)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"the members-only body", response.content)

    def test_a_deactivated_member_is_a_stranger_again(self):
        self.ada.is_active = False
        self.ada.save(update_fields=["is_active"])
        request = self._request("post")
        request.session["member_id"] = self.ada.pk

        with self.assertRaises(PermissionDenied):
            self.gated(request)

        self.assertNotIn("member_id", request.session)


class IdentityIsSeparateFromAdminTests(TestCase):
    """Two session keys, two gates, no relationship between them.

    Decision #5: picking a name is not a claim to be trusted, and the PIN is
    not a claim about who you are.
    """

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")

    def test_identifying_does_not_grant_admin_mode(self):
        self.client.post(reverse("club:identify"), {"member": self.ada.pk})

        response = self.client.post(
            reverse("club:member_toggle", args=[self.ada.pk])
        )

        self.assertEqual(response.status_code, 403)

    def test_admin_mode_does_not_identify_anyone(self):
        session = self.client.session
        session["is_club_admin"] = True
        session.save()

        response = self.client.get(reverse("club:home"))

        self.assertIsNone(response.context["current_member"])

    def test_leaving_admin_mode_leaves_the_identity_alone(self):
        session = self.client.session
        session["is_club_admin"] = True
        session["member_id"] = self.ada.pk
        session.save()

        self.client.post(reverse("club:admin_exit"))

        self.assertEqual(self.client.session["member_id"], self.ada.pk)

    def test_being_forgotten_leaves_admin_mode_alone(self):
        session = self.client.session
        session["is_club_admin"] = True
        session["member_id"] = self.ada.pk
        session.save()

        self.client.post(reverse("club:forget_me"))

        self.assertIs(self.client.session["is_club_admin"], True)


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
            tuple(response.context["cl"].list_display)[-7:],
            (
                "title",
                "author",
                "is_current",
                "started_on",
                "finished_on",
                "rating",
                "total_pages",
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
