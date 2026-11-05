"""The Agree reaction on top-level notes of the current book (#33)."""

from datetime import date

from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .helpers import enter_admin
from ..models import Answer, AnswerReply, Book, Member, Note, Question, Reaction


class ReactionBase(TestCase):
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
        cls.note = Note.objects.create(book=cls.book, author=cls.ada, body="Lovely")

    def identify(self, member, client=None):
        client = client or self.client
        session = client.session
        session["member_id"] = member.pk
        session.save()

    def react(self, note=None, **kwargs):
        note = note or self.note
        return self.client.post(reverse("club:note_react", args=[note.pk]), **kwargs)


class ReactionModelTests(ReactionBase):
    def test_a_member_cannot_hold_two_reactions_on_one_note(self):
        Reaction.objects.create(note=self.note, member=self.bob)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Reaction.objects.create(note=self.note, member=self.bob)

    def test_deleting_a_note_deletes_its_reactions(self):
        Reaction.objects.create(note=self.note, member=self.bob)
        self.note.delete()
        self.assertEqual(Reaction.objects.count(), 0)

    def test_a_member_who_has_reacted_cannot_be_deleted(self):
        Reaction.objects.create(note=self.note, member=self.bob)
        with self.assertRaises(ProtectedError):
            self.bob.delete()


class ReactionToggleTests(ReactionBase):
    def test_agreeing_adds_one_reaction_and_redirects_to_the_notes(self):
        self.identify(self.bob)
        response = self.react()
        self.assertRedirects(response, reverse("club:notes"))
        self.assertEqual(
            Reaction.objects.filter(note=self.note, member=self.bob).count(), 1
        )

    def test_agreeing_again_removes_the_reaction(self):
        self.identify(self.bob)
        self.react()
        response = self.react()
        self.assertRedirects(response, reverse("club:notes"))
        self.assertEqual(Reaction.objects.count(), 0)

    def test_the_page_shows_the_new_count(self):
        self.identify(self.bob)
        response = self.react(follow=True)
        self.assertContains(response, "Agree (1)")

    def test_a_note_with_no_reactions_shows_zero(self):
        response = self.client.get(reverse("club:notes"))
        self.assertContains(response, "Agree (0)")

    def test_two_members_make_a_count_of_two(self):
        Reaction.objects.create(note=self.note, member=self.ada)
        self.identify(self.bob)
        response = self.react(follow=True)
        self.assertContains(response, "Agree (2)")

    def test_another_members_reaction_is_not_my_own_state(self):
        Reaction.objects.create(note=self.note, member=self.ada)
        self.identify(self.bob)
        response = self.client.get(reverse("club:notes"))
        self.assertContains(response, "Agree (1)")
        self.assertContains(response, ">Agree</button>")
        self.assertNotContains(response, ">Undo agree</button>")

    def test_my_own_reaction_offers_undo(self):
        Reaction.objects.create(note=self.note, member=self.bob)
        self.identify(self.bob)
        response = self.client.get(reverse("club:notes"))
        self.assertContains(response, ">Undo agree</button>")

    def test_a_member_may_agree_with_their_own_note(self):
        self.identify(self.ada)
        self.react()
        self.assertEqual(Reaction.objects.filter(member=self.ada).count(), 1)

    def test_a_deactivated_members_reaction_still_counts(self):
        Reaction.objects.create(note=self.note, member=self.bob)
        self.bob.is_active = False
        self.bob.save()
        response = self.client.get(reverse("club:notes"))
        self.assertContains(response, "Agree (1)")

    def test_a_deactivated_members_stale_session_cannot_react(self):
        self.identify(self.bob)
        self.bob.is_active = False
        self.bob.save()
        response = self.react()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Reaction.objects.count(), 0)

    def test_the_removal_message_does_not_mention_reactions(self):
        Reaction.objects.create(note=self.note, member=self.bob)
        self.identify(self.ada)
        response = self.client.post(
            reverse("club:note_delete", args=[self.note.pk]), follow=True
        )
        self.assertContains(response, "Note removed.")
        self.assertNotContains(response, "reaction")


class ReactionGateTests(ReactionBase):
    def test_an_unidentified_post_is_refused_and_writes_nothing(self):
        response = self.react()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Reaction.objects.count(), 0)

    def test_an_unidentified_viewer_sees_the_count_but_no_button(self):
        Reaction.objects.create(note=self.note, member=self.bob)
        response = self.client.get(reverse("club:notes"))
        self.assertContains(response, "Agree (1)")
        self.assertNotContains(
            response, reverse("club:note_react", args=[self.note.pk])
        )

    def test_a_get_is_a_405_and_changes_nothing(self):
        self.identify(self.bob)
        response = self.client.get(reverse("club:note_react", args=[self.note.pk]))
        self.assertEqual(response.status_code, 405)
        self.assertEqual(Reaction.objects.count(), 0)

    def test_the_post_requires_a_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        self.identify(self.bob, client)
        response = client.post(reverse("club:note_react", args=[self.note.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Reaction.objects.count(), 0)


class ReactionRefusalTests(ReactionBase):
    def setUp(self):
        self.identify(self.bob)

    def assertRefused(self, response):
        self.assertRedirects(
            response, reverse("club:notes"), fetch_redirect_response=False
        )
        self.assertEqual(Reaction.objects.count(), 0)

    def test_a_reply_cannot_be_reacted_to(self):
        reply = Note.objects.create(
            book=self.book, author=self.ada, body="Re", parent=self.note
        )
        self.assertRefused(self.react(reply))

    def test_a_missing_note_is_refused(self):
        response = self.client.post(reverse("club:note_react", args=[99999]))
        self.assertRefused(response)

    def test_a_note_on_a_finished_book_is_refused(self):
        old = Book.objects.create(
            title="Emma",
            author="Austen",
            started_on=date(2024, 1, 1),
            finished_on=date(2024, 2, 1),
        )
        note = Note.objects.create(book=old, author=self.ada, body="Old")
        self.assertRefused(self.react(note))

    def test_a_non_numeric_id_writes_nothing(self):
        response = self.client.post("/notes/abc/react/", follow=False)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Reaction.objects.count(), 0)

    def test_a_refusal_carries_a_message(self):
        reply = Note.objects.create(
            book=self.book, author=self.ada, body="Re", parent=self.note
        )
        response = self.react(reply, follow=True)
        self.assertContains(response, "Only a top-level note")


class ReactionFilterTests(ReactionBase):
    def test_the_chapter_filter_still_works_with_counts(self):
        Note.objects.create(
            book=self.book, author=self.ada, body="Chapter two note", chapter=2
        )
        Reaction.objects.create(note=self.note, member=self.bob)
        response = self.client.get(reverse("club:notes") + "?chapter=2")
        self.assertContains(response, "Chapter two note")
        self.assertNotContains(response, "Lovely")
        self.assertContains(response, "Agree (0)")


class ReactionQueryTests(ReactionBase):
    def _make_notes(self, n):
        for i in range(n):
            note = Note.objects.create(book=self.book, author=self.ada, body=f"n{i}")
            Reaction.objects.create(note=note, member=self.ada)
            Reaction.objects.create(note=note, member=self.bob)

    def _count_queries(self):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(reverse("club:notes"))
        self.assertEqual(response.status_code, 200)
        return len(ctx)

    def test_query_count_is_constant_as_notes_grow(self):
        self.identify(self.bob)
        self._make_notes(1)
        small = self._count_queries()
        self._make_notes(20)
        large = self._count_queries()
        self.assertEqual(small, large)

    def test_the_count_is_pinned(self):
        self.identify(self.bob)
        self._make_notes(2)
        # Six before reactions existed (book twice, session, member, notes,
        # replies prefetch) plus one for the viewer's reacted note ids.
        with self.assertNumQueries(7):
            self.client.get(reverse("club:notes"))

    def test_the_order_is_still_newest_first(self):
        Note.objects.create(book=self.book, author=self.ada, body="Newer one")
        Reaction.objects.create(note=self.note, member=self.bob)
        content = self.client.get(reverse("club:notes")).content.decode()
        self.assertLess(content.index("Newer one"), content.index("Lovely"))


class ArchiveReactionCountTests(ReactionBase):
    """The archive prints each top-level note's final count, read-only (#58)."""

    def archive(self, book=None):
        book = book or self.book
        return self.client.get(reverse("club:history_detail", args=[book.pk]))

    def finish(self):
        self.book.is_current = False
        self.book.finished_on = date(2025, 10, 1)
        self.book.save()

    def test_a_reacted_note_shows_its_count_in_the_byline(self):
        Reaction.objects.create(note=self.note, member=self.ada)
        Reaction.objects.create(note=self.note, member=self.bob)
        self.finish()
        self.assertContains(self.archive(), "Agree (2)")

    def test_an_unreacted_note_shows_no_agree_text_at_all(self):
        self.finish()
        response = self.archive()
        self.assertContains(response, "Lovely")
        self.assertNotContains(response, "Agree")

    def test_no_form_button_or_react_link_for_anyone(self):
        Reaction.objects.create(note=self.note, member=self.bob)
        self.finish()
        react_url = reverse("club:note_react", args=[self.note.pk])
        viewers = {"anonymous": None, "member": self.ada, "admin": self.ada}
        for who, member in viewers.items():
            with self.subTest(viewer=who):
                client = Client()
                if member:
                    session = client.session
                    session["member_id"] = member.pk
                    if who == "admin":
                        enter_admin(session)
                    session.save()
                response = client.get(
                    reverse("club:history_detail", args=[self.book.pk])
                )
                self.assertContains(response, "Agree (1)")
                self.assertNotContains(response, react_url)
                self.assertNotContains(response, "Undo agree")
                self.assertNotContains(response, "Agree</button>")

    def test_a_deactivated_reactors_agreement_is_counted(self):
        Reaction.objects.create(note=self.note, member=self.bob)
        self.bob.is_active = False
        self.bob.save()
        self.finish()
        self.assertContains(self.archive(), "Agree (1)")

    def test_a_reply_shows_no_count_even_with_a_reaction_row(self):
        reply = Note.objects.create(
            book=self.book, author=self.bob, body="Replying", parent=self.note
        )
        Reaction.objects.create(note=reply, member=self.ada)
        self.finish()
        response = self.archive()
        self.assertContains(response, "Replying")
        self.assertNotContains(response, "Agree")

    def test_each_note_shows_its_own_count(self):
        other = Note.objects.create(book=self.book, author=self.bob, body="Second")
        Reaction.objects.create(note=self.note, member=self.ada)
        Reaction.objects.create(note=other, member=self.ada)
        Reaction.objects.create(note=other, member=self.bob)
        self.finish()
        content = self.archive().content.decode()
        self.assertEqual(content.count("Agree (1)"), 1)
        self.assertEqual(content.count("Agree (2)"), 1)
        self.assertLess(content.index("Agree (2)"), content.index("Agree (1)"))

    def test_the_current_book_preview_shows_the_count_without_a_button(self):
        Reaction.objects.create(note=self.note, member=self.bob)
        self.identify(self.ada)
        response = self.archive()
        self.assertContains(response, "Agree (1)")
        self.assertNotContains(response, reverse("club:note_react", args=[self.note.pk]))

    def test_the_count_matches_the_notes_page_before_and_after_finishing(self):
        Reaction.objects.create(note=self.note, member=self.ada)
        Reaction.objects.create(note=self.note, member=self.bob)
        self.assertContains(self.client.get(reverse("club:notes")), "Agree (2)")
        self.finish()
        self.assertContains(self.archive(), "Agree (2)")

    def test_a_reopened_and_refinished_book_keeps_its_reactions(self):
        Reaction.objects.create(note=self.note, member=self.ada)
        Reaction.objects.create(note=self.note, member=self.bob)
        self.finish()
        session = self.client.session
        enter_admin(session)
        session.save()
        self.client.post(reverse("club:book_reopen", args=[self.book.pk]))
        self.book.refresh_from_db()
        self.assertTrue(self.book.is_current)
        self.finish()
        self.assertContains(self.archive(), "Agree (2)")


class ArchiveReactionQueryTests(ReactionBase):
    """Regression guards: these pass before #58 because `_top_level_notes`
    already annotates `agree_count`. They are not red tests; they pin that
    printing the count adds no query."""

    def setUp(self):
        self.book.is_current = False
        self.book.finished_on = date(2025, 10, 1)
        self.book.save()
        self.url = reverse("club:history_detail", args=[self.book.pk])

    def _add_notes(self, n):
        for i in range(n):
            note = Note.objects.create(book=self.book, author=self.ada, body=f"n{i}")
            Reaction.objects.create(note=note, member=self.ada)
            Reaction.objects.create(note=note, member=self.bob)
            Note.objects.create(
                book=self.book, author=self.bob, body=f"r{i}", parent=note
            )

    def _queries(self):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        return len(ctx)

    def test_the_archive_is_pinned_at_eight_queries(self):
        question = Question.objects.create(book=self.book, text="Why?", position=1)
        answer = Answer.objects.create(question=question, member=self.ada, body="Yes")
        AnswerReply.objects.create(answer=answer, author=self.bob, body="Agreed")
        self._add_notes(2)
        with self.assertNumQueries(8):
            self.client.get(self.url)

    def test_query_count_is_equal_with_one_note_and_twenty_one(self):
        Note.objects.filter(book=self.book).delete()
        self._add_notes(1)
        small = self._queries()
        self._add_notes(20)
        self.assertEqual(small, self._queries())
