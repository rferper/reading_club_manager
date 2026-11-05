"""One level of replies on notes: the model rules, posting, display, removal."""

from datetime import date

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .helpers import enter_admin
from ..models import Book, Member, Note


class ReplyTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.bob = Member.objects.create(name="Bob")
        cls.book = Book.objects.create(
            title="Middlemarch",
            author="George Eliot",
            started_on=date(2025, 9, 1),
            is_current=True,
        )
        cls.old_book = Book.objects.create(title="Piranesi", author="Susanna Clarke")
        cls.note = Note.objects.create(book=cls.book, author=cls.ada, body="Top note")

    def identify(self, member, admin=False):
        session = self.client.session
        session["member_id"] = member.pk
        if admin:
            enter_admin(session)
        session.save()

    def reply_to(self, parent, body="A reply"):
        return self.client.post(
            reverse("club:notes"),
            {"parent": parent, "body": body},
        )


class ReplyModelTests(ReplyTestBase):
    def test_a_top_level_note_has_no_parent(self):
        self.assertIsNone(self.note.parent)

    def test_a_reply_is_reachable_from_its_note(self):
        reply = Note.objects.create(
            book=self.book, author=self.bob, body="r", parent=self.note
        )
        self.assertEqual(list(self.note.replies.all()), [reply])

    def test_a_reply_to_a_reply_is_refused_by_clean(self):
        reply = Note.objects.create(
            book=self.book, author=self.bob, body="r", parent=self.note
        )
        nested = Note(book=self.book, author=self.ada, body="n", parent=reply)
        with self.assertRaises(ValidationError):
            nested.full_clean()

    def test_a_reply_on_another_book_than_its_note_is_refused_by_clean(self):
        stray = Note(book=self.old_book, author=self.ada, body="n", parent=self.note)
        with self.assertRaises(ValidationError):
            stray.full_clean()

    def test_deleting_a_note_deletes_its_replies(self):
        Note.objects.create(book=self.book, author=self.bob, body="r", parent=self.note)
        self.note.delete()
        self.assertEqual(Note.objects.count(), 0)

    def test_deleting_a_reply_leaves_its_note(self):
        reply = Note.objects.create(
            book=self.book, author=self.bob, body="r", parent=self.note
        )
        reply.delete()
        self.assertTrue(Note.objects.filter(pk=self.note.pk).exists())


class PostingReplyTests(ReplyTestBase):
    def test_a_member_sees_a_reply_form_under_a_note(self):
        self.identify(self.bob)
        response = self.client.get(reverse("club:notes"))
        self.assertContains(response, ">Reply</button>")

    def test_a_stranger_sees_no_reply_form(self):
        response = self.client.get(reverse("club:notes"))
        self.assertNotContains(response, ">Reply</button>")
        self.assertContains(response, "Say who you are")

    def test_a_valid_reply_is_saved_with_session_author_and_parent_book(self):
        self.identify(self.bob)
        response = self.reply_to(self.note.pk)

        self.assertRedirects(response, reverse("club:notes"))
        reply = Note.objects.get(parent=self.note)
        self.assertEqual(reply.author, self.bob)
        self.assertEqual(reply.book, self.book)
        self.assertEqual(reply.body, "A reply")

    def test_a_valid_reply_shows_a_success_message(self):
        self.identify(self.bob)
        response = self.client.post(
            reverse("club:notes"),
            {"parent": self.note.pk, "body": "x"},
            follow=True,
        )
        self.assertContains(response, "Reply posted.")

    def test_an_empty_reply_errors_on_that_notes_form_only(self):
        other = Note.objects.create(book=self.book, author=self.ada, body="Other")
        self.identify(self.bob)
        response = self.reply_to(self.note.pk, "   ")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Note.objects.count(), 2)
        self.assertContains(response, "A reply needs something in it.", count=1)
        forms = {row["note"].pk: row["reply_form"] for row in response.context["rows"]}
        self.assertTrue(forms[self.note.pk].is_bound)
        self.assertFalse(forms[other.pk].is_bound)
        self.assertFalse(response.context["form"].is_bound)

    def test_an_unidentified_reply_is_403_and_writes_nothing(self):
        response = self.reply_to(self.note.pk)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Note.objects.count(), 1)

    def test_bad_parents_come_back_as_a_form_error_not_a_500(self):
        reply = Note.objects.create(
            book=self.book, author=self.ada, body="r", parent=self.note
        )
        old_note = Note.objects.create(book=self.old_book, author=self.ada, body="o")
        self.identify(self.bob)
        before = Note.objects.count()

        for bad in ["", "abc", 99999, reply.pk, old_note.pk]:
            with self.subTest(parent=bad):
                response = self.reply_to(bad)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Choose a note to reply to.")
        self.assertEqual(Note.objects.count(), before)

    def test_with_no_current_book_a_reply_redirects_home(self):
        Book.objects.update(is_current=False)
        self.identify(self.bob)
        response = self.reply_to(self.note.pk)

        self.assertRedirects(response, reverse("club:home"))
        self.assertEqual(Note.objects.count(), 1)


class ReplyDisplayTests(ReplyTestBase):
    def test_replies_sit_under_their_note_oldest_first(self):
        Note.objects.create(
            book=self.book, author=self.bob, body="first reply", parent=self.note
        )
        Note.objects.create(
            book=self.book, author=self.ada, body="second reply", parent=self.note
        )
        Note.objects.create(book=self.book, author=self.ada, body="Newer top")

        response = self.client.get(reverse("club:notes"))
        content = response.content.decode()

        self.assertLess(content.index("Newer top"), content.index("Top note"))
        self.assertLess(content.index("Top note"), content.index("first reply"))
        self.assertLess(content.index("first reply"), content.index("second reply"))
        self.assertEqual(len(response.context["rows"]), 2)

    def test_a_note_with_no_replies_shows_no_placeholder(self):
        response = self.client.get(reverse("club:notes"))
        self.assertNotContains(response, "No replies")

    def test_an_empty_book_keeps_its_empty_state(self):
        Note.objects.all().delete()
        response = self.client.get(reverse("club:notes"))
        self.assertContains(response, "No notes on Middlemarch yet")

    def test_a_reply_body_is_escaped(self):
        Note.objects.create(
            book=self.book, author=self.bob, body="<script>x</script>", parent=self.note
        )
        response = self.client.get(reverse("club:notes"))
        self.assertNotContains(response, "<script>x</script>")
        self.assertContains(response, "&lt;script&gt;x&lt;/script&gt;")

    def test_a_deactivated_authors_reply_keeps_their_name(self):
        Note.objects.create(
            book=self.book, author=self.bob, body="gone", parent=self.note
        )
        self.bob.is_active = False
        self.bob.save(update_fields=["is_active"])
        response = self.client.get(reverse("club:notes"))
        self.assertContains(response, "Bob")

    def test_the_archive_lists_replies_read_only_and_not_as_top_level(self):
        old = Note.objects.create(book=self.old_book, author=self.ada, body="Old top")
        Note.objects.create(
            book=self.old_book, author=self.bob, body="Old reply", parent=old
        )
        self.identify(self.bob)
        response = self.client.get(
            reverse("club:history_detail", args=[self.old_book.pk])
        )

        self.assertContains(response, "Old reply", count=1)
        self.assertEqual(len(response.context["notes"]), 1)
        self.assertNotContains(response, ">Reply</button>")
        self.assertNotContains(response, "Remove")

    def test_notes_page_query_count_does_not_grow(self):
        """Decision #19: replies come in one prefetch, whatever the thread size."""
        self.identify(self.bob)
        with CaptureQueriesContext(connection) as small:
            self.client.get(reverse("club:notes"))

        for i in range(5):
            top = Note.objects.create(book=self.book, author=self.ada, body=f"t{i}")
            for j in range(4):
                Note.objects.create(
                    book=self.book, author=self.bob, body=f"r{i}{j}", parent=top
                )

        with CaptureQueriesContext(connection) as large:
            self.client.get(reverse("club:notes"))

        self.assertEqual(len(small), len(large))


class ReplyRemovalTests(ReplyTestBase):
    def setUp(self):
        self.reply = Note.objects.create(
            book=self.book, author=self.bob, body="mine", parent=self.note
        )

    def remove(self, note):
        return self.client.post(reverse("club:note_delete", args=[note.pk]))

    def test_the_author_may_remove_their_reply(self):
        self.identify(self.bob)
        self.assertRedirects(self.remove(self.reply), reverse("club:notes"))
        self.assertFalse(Note.objects.filter(pk=self.reply.pk).exists())
        self.assertTrue(Note.objects.filter(pk=self.note.pk).exists())

    def test_an_admin_may_remove_a_reply(self):
        self.identify(self.ada, admin=True)
        self.remove(self.reply)
        self.assertFalse(Note.objects.filter(pk=self.reply.pk).exists())

    def test_another_member_removing_a_reply_is_403(self):
        self.identify(self.ada)
        self.assertEqual(self.remove(self.reply).status_code, 403)
        self.assertTrue(Note.objects.filter(pk=self.reply.pk).exists())

    def test_a_note_with_replies_states_the_cascade_on_its_button(self):
        self.identify(self.ada)
        response = self.client.get(reverse("club:notes"))
        self.assertContains(response, "Remove (also removes 1 reply)")

    def test_removing_a_note_says_how_many_replies_went_with_it(self):
        Note.objects.create(
            book=self.book, author=self.ada, body="r2", parent=self.note
        )
        self.identify(self.ada)
        response = self.client.post(
            reverse("club:note_delete", args=[self.note.pk]), follow=True
        )
        self.assertContains(response, "2 replies")
        self.assertEqual(Note.objects.count(), 0)
