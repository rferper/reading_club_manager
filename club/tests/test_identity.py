"""Who the session says the viewer is, and the gate that requires one."""

from urllib.parse import urlencode

from django.contrib.sessions.middleware import SessionMiddleware
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase
from django.urls import reverse

from ..decorators import require_member
from ..models import Member


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
