"""The home page's "Since you last looked" panel and its "Mark as seen" POST."""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from ..models import Answer, Book, Member, Question

PANEL = "Since you last looked"


class WhatsNewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.bob = Member.objects.create(name="Bob")

    def setUp(self):
        # A current book made an hour ago, and Ada last looked a minute ago.
        # Not 'now': the clock can tick coarsely and tie with a new row.
        self.book = Book.objects.create(
            title="Middlemarch", author="George Eliot", is_current=True
        )
        Book.objects.filter(pk=self.book.pk).update(
            created_on=timezone.now() - timedelta(hours=1)
        )
        Member.objects.filter(pk=self.ada.pk).update(
            notifications_seen_at=timezone.now() - timedelta(minutes=1)
        )
        self.ada.refresh_from_db()

    def as_member(self, member):
        session = self.client.session
        session["member_id"] = member.pk
        session.save()

    def home(self):
        return self.client.get(reverse("club:home"))

    def test_panel_lists_a_new_question(self):
        Question.objects.create(book=self.book, text="Was Casaubon fair?")
        self.as_member(self.ada)

        response = self.home()

        self.assertContains(response, PANEL)
        self.assertContains(response, "Was Casaubon fair?")
        self.assertContains(response, reverse("club:questions"))

    def test_panel_counts_new_answers_by_other_members(self):
        question = Question.objects.create(book=self.book, text="Q")
        Answer.objects.create(question=question, member=self.bob, body="Yes")
        self.as_member(self.ada)

        self.assertContains(self.home(), "1 new answer")

    def test_panel_announces_a_book_started_after_the_marker(self):
        Member.objects.filter(pk=self.ada.pk).update(
            notifications_seen_at=timezone.now() - timedelta(days=1)
        )
        self.as_member(self.ada)

        self.assertContains(self.home(), "A new book started: Middlemarch")

    def test_own_answers_never_appear(self):
        question = Question.objects.create(book=self.book, text="Q")
        Answer.objects.create(question=question, member=self.ada, body="Mine")
        Question.objects.filter(pk=question.pk).update(
            created_on=timezone.now() - timedelta(days=1)
        )
        self.as_member(self.ada)

        self.assertNotContains(self.home(), PANEL)

    def test_an_edited_answer_does_not_reappear(self):
        question = Question.objects.create(book=self.book, text="Q")
        Question.objects.filter(pk=question.pk).update(
            created_on=timezone.now() - timedelta(days=1)
        )
        answer = Answer.objects.create(question=question, member=self.bob, body="a")
        Answer.objects.filter(pk=answer.pk).update(
            created_on=timezone.now() - timedelta(days=1)
        )
        answer.refresh_from_db()
        answer.body = "edited"
        answer.save()  # bumps updated_on only
        self.as_member(self.ada)

        self.assertNotContains(self.home(), PANEL)

    def test_nothing_new_renders_no_panel(self):
        self.as_member(self.ada)

        self.assertNotContains(self.home(), PANEL)

    def test_no_current_book_renders_no_panel(self):
        Book.objects.update(is_current=False)
        self.as_member(self.ada)

        response = self.home()

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, PANEL)

    def test_questions_on_a_finished_book_do_not_count(self):
        old = Book.objects.create(title="Old", author="X")
        Question.objects.create(book=old, text="Archived question")
        self.as_member(self.ada)

        self.assertNotContains(self.home(), PANEL)

    def test_unidentified_viewer_sees_no_panel(self):
        Question.objects.create(book=self.book, text="Was Casaubon fair?")

        response = self.home()

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, PANEL)

    def test_deactivated_member_sees_no_panel(self):
        Question.objects.create(book=self.book, text="Was Casaubon fair?")
        self.as_member(self.ada)
        Member.objects.filter(pk=self.ada.pk).update(is_active=False)

        self.assertNotContains(self.home(), PANEL)

    def test_null_marker_counts_from_the_start_of_joined_on(self):
        Member.objects.filter(pk=self.bob.pk).update(
            joined_on=timezone.localdate() - timedelta(days=3)
        )
        Question.objects.create(book=self.book, text="Fresh question")
        old = Question.objects.create(book=self.book, text="Ancient question")
        Question.objects.filter(pk=old.pk).update(
            created_on=timezone.now() - timedelta(days=10)
        )
        self.as_member(self.bob)

        response = self.home()

        self.assertContains(response, "Fresh question")
        self.assertNotContains(response, "Ancient question")

    def test_loading_pages_never_stamps_the_marker(self):
        Question.objects.create(book=self.book, text="Q")
        self.as_member(self.bob)

        for name in ("home", "questions", "notes", "progress"):
            self.client.get(reverse(f"club:{name}"))

        self.bob.refresh_from_db()
        self.assertIsNone(self.bob.notifications_seen_at)


class MarkSeenTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")

    def setUp(self):
        self.book = Book.objects.create(
            title="Middlemarch", author="George Eliot", is_current=True
        )
        Question.objects.create(book=self.book, text="Was Casaubon fair?")

    def as_ada(self):
        session = self.client.session
        session["member_id"] = self.ada.pk
        session.save()

    def test_post_stamps_redirects_and_clears_the_panel(self):
        self.as_ada()
        self.assertContains(self.client.get(reverse("club:home")), PANEL)

        response = self.client.post(reverse("club:mark_seen"))

        self.assertRedirects(response, reverse("club:home"))
        self.ada.refresh_from_db()
        self.assertIsNotNone(self.ada.notifications_seen_at)
        self.assertNotContains(self.client.get(reverse("club:home")), PANEL)

    def test_get_is_refused_and_changes_nothing(self):
        self.as_ada()

        response = self.client.get(reverse("club:mark_seen"))

        self.assertEqual(response.status_code, 405)
        self.ada.refresh_from_db()
        self.assertIsNone(self.ada.notifications_seen_at)

    def test_post_without_csrf_token_is_rejected(self):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        session = client.session
        session["member_id"] = self.ada.pk
        session.save()

        response = client.post(reverse("club:mark_seen"))

        self.assertEqual(response.status_code, 403)
        self.ada.refresh_from_db()
        self.assertIsNone(self.ada.notifications_seen_at)

    def test_post_with_nobody_identified_changes_nothing_and_redirects(self):
        response = self.client.post(reverse("club:mark_seen"))

        self.assertRedirects(response, reverse("club:home"))
        self.ada.refresh_from_db()
        self.assertIsNone(self.ada.notifications_seen_at)
