from datetime import date

from django.contrib.auth.models import User
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import IntegrityError, transaction
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse
from django.utils import formats, timezone

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
