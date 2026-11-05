"""Deleting a book created by mistake: the gate, the confirmation, the cascade."""

from datetime import date

from django.contrib.messages import get_messages
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .helpers import enter_admin
from ..models import (
    Answer,
    AnswerReply,
    Book,
    Member,
    MemberRating,
    Note,
    Progress,
    ProgressEntry,
    Question,
    Reaction,
)

DEPENDENTS = (
    Progress,
    ProgressEntry,
    Note,
    Reaction,
    Question,
    Answer,
    AnswerReply,
    MemberRating,
)

# How each dependent type reaches its book, for counting one book's rows.
BOOK_PATH = {
    Progress: "book",
    ProgressEntry: "progress__book",
    Note: "book",
    Reaction: "note__book",
    Question: "book",
    Answer: "question__book",
    AnswerReply: "answer__question__book",
    MemberRating: "book",
}


def load(book, ada, bob):
    """Give `book` one row of every dependent type, plus a note reply."""
    progress = Progress.objects.create(book=book, member=ada, pages_read=10)
    ProgressEntry.objects.create(progress=progress, pages_read=5)
    ProgressEntry.objects.create(progress=progress, pages_read=10)
    note = Note.objects.create(book=book, author=ada, body="A thought")
    Note.objects.create(book=book, author=bob, body="A reply", parent=note)
    Reaction.objects.create(note=note, member=bob)
    question = Question.objects.create(book=book, text="Why?", position=1)
    answer = Answer.objects.create(question=question, member=ada, body="Because")
    AnswerReply.objects.create(answer=answer, author=bob, body="Fair")
    MemberRating.objects.create(book=book, member=ada, score=4)
    MemberRating.objects.create(book=book, member=bob, score=5)


def snapshot():
    return {m.__name__: m.objects.count() for m in (Book, Member) + DEPENDENTS}


class BookDeleteBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.bob = Member.objects.create(name="Bob")
        cls.current = Book.objects.create(
            title="Middlemarch", author="George Eliot", is_current=True
        )
        cls.old = Book.objects.create(
            title="Piranesi",
            author="Susanna Clarke",
            finished_on=date(2025, 1, 1),
            rating=4,
        )

    def admin(self):
        session = self.client.session
        session["member_id"] = self.ada.pk
        enter_admin(session)
        session.save()

    def url(self, book):
        return reverse("club:book_delete", args=[book.pk])


class GateTests(BookDeleteBase):
    def test_non_admin_post_is_refused_and_book_survives(self):
        load(self.current, self.ada, self.bob)
        before = snapshot()
        response = self.client.post(self.url(self.current))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(snapshot(), before)
        self.assertTrue(Book.objects.filter(pk=self.current.pk).exists())

    def test_non_admin_get_redirects_to_pin_with_next(self):
        response = self.client.get(self.url(self.current))
        expected = reverse("club:admin_pin") + "?next=" + self.url(self.current)
        self.assertRedirects(response, expected, fetch_redirect_response=False)

    def test_put_is_405(self):
        self.admin()
        self.assertEqual(self.client.put(self.url(self.current)).status_code, 405)
        self.assertTrue(Book.objects.filter(pk=self.current.pk).exists())

    def test_delete_method_is_405(self):
        self.admin()
        self.assertEqual(self.client.delete(self.url(self.current)).status_code, 405)

    def test_unknown_pk_is_404_for_get_and_post(self):
        self.admin()
        url = reverse("club:book_delete", args=[99999])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url).status_code, 404)


class ConfirmationTests(BookDeleteBase):
    def test_admin_get_deletes_nothing(self):
        load(self.current, self.ada, self.bob)
        self.admin()
        before = snapshot()
        response = self.client.get(self.url(self.current))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(snapshot(), before)

    def test_page_names_book_and_says_current(self):
        self.admin()
        response = self.client.get(self.url(self.current))
        self.assertContains(response, "Middlemarch")
        self.assertContains(response, "George Eliot")
        self.assertContains(response, "current read")

    def test_archived_book_is_not_called_current(self):
        self.admin()
        response = self.client.get(self.url(self.old))
        self.assertContains(response, "Piranesi")
        self.assertNotContains(response, "current read")

    def test_empty_book_says_nothing_else_is_attached(self):
        self.admin()
        response = self.client.get(self.url(self.old))
        self.assertContains(response, "nothing else is attached")

    def test_counts_match_a_loaded_book(self):
        load(self.current, self.ada, self.bob)
        self.admin()
        response = self.client.get(self.url(self.current))
        self.assertNotContains(response, "nothing else is attached")
        self.assertEqual(
            response.context["counts"],
            {
                "progress": 1,
                "entries": 2,
                "notes": 1,
                "note_replies": 1,
                "reactions": 1,
                "questions": 1,
                "answers": 1,
                "answer_replies": 1,
                "ratings": 2,
            },
        )
        self.assertContains(response, "2 progress entries")
        self.assertContains(response, "2 member scores")
        self.assertContains(response, "1 question")

    def test_zero_lines_are_omitted(self):
        Note.objects.create(book=self.old, author=self.ada, body="Hi")
        self.admin()
        response = self.client.get(self.url(self.old))
        self.assertContains(response, "1 note")
        self.assertNotContains(response, "progress entries")
        self.assertNotContains(response, "member scores")

    def test_keep_it_link_goes_home_for_current_and_detail_for_archived(self):
        self.admin()
        home = reverse("club:home")
        detail = reverse("club:history_detail", args=[self.old.pk])
        self.assertContains(
            self.client.get(self.url(self.current)), f'href="{home}">Keep it'
        )
        self.assertContains(
            self.client.get(self.url(self.old)), f'href="{detail}">Keep it'
        )

    def test_form_posts_with_csrf(self):
        self.admin()
        response = self.client.get(self.url(self.old))
        self.assertContains(response, 'method="post"')
        self.assertContains(response, "csrfmiddlewaretoken")

    def test_query_count_is_fixed(self):
        self.admin()
        self.client.get(self.url(self.old))
        with CaptureQueriesContext(connection) as small:
            self.client.get(self.url(self.old))
        load(self.current, self.ada, self.bob)
        with CaptureQueriesContext(connection) as big:
            self.client.get(self.url(self.current))
        self.assertEqual(len(small), len(big))


class DeleteTests(BookDeleteBase):
    def test_loaded_book_goes_with_no_orphans_and_others_survive(self):
        load(self.current, self.ada, self.bob)
        load(self.old, self.ada, self.bob)
        old_counts = {
            m: m.objects.filter(**{BOOK_PATH[m]: self.old}).count()
            for m in DEPENDENTS
        }
        total = {m: m.objects.count() for m in DEPENDENTS}
        members = Member.objects.count()
        self.admin()
        response = self.client.post(self.url(self.current))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Book.objects.filter(pk=self.current.pk).exists())
        # Everything that remains belongs to the other book.
        for m in DEPENDENTS:
            self.assertEqual(m.objects.count(), old_counts[m], m.__name__)
            self.assertLess(m.objects.count(), total[m], m.__name__)
        self.assertEqual(Member.objects.count(), members)
        self.assertTrue(Book.objects.filter(pk=self.old.pk).exists())

    def test_archived_rated_book_is_deletable_and_redirects_to_history(self):
        load(self.old, self.ada, self.bob)
        self.admin()
        response = self.client.post(self.url(self.old))
        self.assertRedirects(response, reverse("club:history"))
        self.assertFalse(Book.objects.filter(pk=self.old.pk).exists())
        self.assertEqual(Note.objects.count(), 0)

    def test_current_book_redirects_home_and_home_is_empty_state(self):
        self.admin()
        response = self.client.post(self.url(self.current), follow=True)
        self.assertRedirects(response, reverse("club:home"))
        self.assertIsNone(Book.objects.current())
        self.assertContains(response, "No book in progress")

    def test_success_message_names_book_and_totals(self):
        load(self.current, self.ada, self.bob)
        self.admin()
        response = self.client.post(self.url(self.current))
        text = " ".join(str(m) for m in get_messages(response.wsgi_request))
        self.assertIn("Middlemarch", text)
        self.assertIn("2 member scores", text)
        self.assertIn("1 question", text)

    def test_message_for_a_bare_book(self):
        self.admin()
        response = self.client.post(self.url(self.old))
        text = " ".join(str(m) for m in get_messages(response.wsgi_request))
        self.assertIn("Piranesi", text)


class LinkTests(BookDeleteBase):
    def test_home_link_admin_only(self):
        url = self.url(self.current)
        self.assertNotContains(self.client.get(reverse("club:home")), url)
        self.admin()
        self.assertContains(self.client.get(reverse("club:home")), url)

    def test_history_detail_link_admin_only(self):
        detail = reverse("club:history_detail", args=[self.old.pk])
        url = self.url(self.old)
        self.assertNotContains(self.client.get(detail), url)
        self.admin()
        self.assertContains(self.client.get(detail), url)

    def test_history_list_has_no_delete_link(self):
        self.admin()
        response = self.client.get(reverse("club:history"))
        self.assertNotContains(response, self.url(self.old))
