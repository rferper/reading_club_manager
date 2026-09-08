"""The `Member` model, its admin, and the roster page built on both."""

from datetime import date
from urllib.parse import urlencode

from django.contrib.auth.models import User
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import formats, timezone

from ..models import Member


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
