"""The home page's "Since you last looked" panel and its "Mark as seen" POST."""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from ..models import Answer, Book, Member, Note, Question

PANEL = "Since you last looked"

# Queries on the home page for an identified member, panel included. Before
# #40 it was HOME_QUERIES_BEFORE; the notes aggregate adds exactly one.
HOME_QUERIES_BEFORE = 5
HOME_QUERIES_WITH_PANEL = HOME_QUERIES_BEFORE + 1


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


class NotesInPanelTests(TestCase):
    """New notes and note replies from others (#40). Answer replies are not here."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.bob = Member.objects.create(name="Bob")

    def setUp(self):
        self.book = Book.objects.create(
            title="Middlemarch", author="George Eliot", is_current=True
        )
        Book.objects.filter(pk=self.book.pk).update(
            created_on=timezone.now() - timedelta(hours=1)
        )
        # Ada last looked ten minutes ago; whole-minute offsets avoid clock ties.
        Member.objects.filter(pk=self.ada.pk).update(
            notifications_seen_at=timezone.now() - timedelta(minutes=10)
        )
        self.ada.refresh_from_db()
        session = self.client.session
        session["member_id"] = self.ada.pk
        session.save()

    def note(self, author=None, parent=None, book=None, minutes_ago=5):
        note = Note.objects.create(
            book=book or self.book,
            author=author or self.bob,
            parent=parent,
            body="text",
        )
        Note.objects.filter(pk=note.pk).update(
            created_on=timezone.now() - timedelta(minutes=minutes_ago)
        )
        return note

    def home(self):
        return self.client.get(reverse("club:home"))

    def test_other_members_note_is_counted_and_links_to_notes(self):
        self.note()

        response = self.home()

        self.assertContains(response, PANEL)
        self.assertContains(response, "1 new note")
        self.assertNotContains(response, "new reply")
        self.assertContains(response, f'href="{reverse("club:notes")}">1 new note')

    def test_plural_note_count(self):
        self.note()
        self.note()
        self.note()

        self.assertContains(self.home(), "3 new notes")

    def test_reply_is_counted_separately_from_notes(self):
        top = self.note(author=self.ada, minutes_ago=20)  # before the marker
        self.note(author=self.bob, parent=top)

        response = self.home()

        self.assertContains(response, "1 new reply")
        self.assertNotContains(response, "new note")

    def test_note_and_reply_make_two_items_in_order(self):
        top = self.note()
        self.note(parent=top)
        self.note(parent=top)

        response = self.home()
        html = response.content.decode()

        self.assertContains(response, "1 new note")
        self.assertContains(response, "2 new replies")
        self.assertLess(html.index("1 new note"), html.index("2 new replies"))
        self.assertContains(response, f'href="{reverse("club:notes")}">2 new replies')

    def test_notes_come_after_answers(self):
        question = Question.objects.create(book=self.book, text="Q")
        Answer.objects.create(question=question, member=self.bob, body="A")
        self.note()

        html = self.home().content.decode()

        self.assertLess(html.index("new answer"), html.index("new note"))

    def test_another_members_reply_under_my_note_counts(self):
        mine = self.note(author=self.ada, minutes_ago=20)
        self.note(parent=mine)

        self.assertContains(self.home(), "1 new reply")

    def test_own_note_and_own_reply_produce_no_panel(self):
        top = self.note(author=self.ada)
        self.note(author=self.ada, parent=top)

        self.assertNotContains(self.home(), PANEL)

    def test_only_a_note_makes_the_panel_appear(self):
        self.note()

        self.assertContains(self.home(), PANEL)

    def test_nothing_new_keeps_the_panel_hidden(self):
        self.assertNotContains(self.home(), PANEL)

    def test_note_before_the_marker_is_not_counted(self):
        self.note(minutes_ago=11)  # just before the marker
        self.note(minutes_ago=30)

        self.assertNotContains(self.home(), PANEL)

    def test_marker_is_strict_for_notes_and_replies(self):
        instant = timezone.now().replace(microsecond=0) - timedelta(minutes=5)
        Member.objects.filter(pk=self.ada.pk).update(notifications_seen_at=instant)
        top = self.note(author=self.ada, minutes_ago=60)
        tie_note = self.note()
        tie_reply = self.note(parent=top)
        Note.objects.filter(pk__in=[tie_note.pk, tie_reply.pk]).update(
            created_on=instant
        )

        self.assertNotContains(self.home(), PANEL)

        Note.objects.filter(pk=tie_note.pk).update(
            created_on=instant + timedelta(seconds=1)
        )
        self.assertContains(self.home(), "1 new note")
        self.assertNotContains(self.home(), "new reply")

        Note.objects.filter(pk=tie_reply.pk).update(
            created_on=instant + timedelta(seconds=1)
        )
        self.assertContains(self.home(), "1 new reply")

    def test_note_on_a_finished_book_is_not_counted(self):
        old = Book.objects.create(title="Old", author="X")
        self.note(book=old)

        self.assertNotContains(self.home(), PANEL)

    def test_deleting_a_note_drops_it_from_the_count(self):
        keep = self.note()
        gone = self.note()
        self.assertContains(self.home(), "2 new notes")

        gone.delete()

        response = self.home()
        self.assertContains(response, "1 new note")
        self.assertNotContains(response, "2 new notes")
        keep.delete()
        self.assertNotContains(self.home(), PANEL)

    def test_deleting_a_note_cascades_its_replies_out_of_the_count(self):
        top = self.note()
        self.note(parent=top)
        self.assertContains(self.home(), "1 new reply")

        top.delete()

        self.assertNotContains(self.home(), PANEL)

    def test_deactivated_author_still_counts(self):
        self.note()
        Member.objects.filter(pk=self.bob.pk).update(is_active=False)

        self.assertContains(self.home(), "1 new note")

    def test_null_marker_counts_from_the_start_of_joined_on(self):
        Member.objects.filter(pk=self.bob.pk).update(
            joined_on=timezone.localdate() - timedelta(days=3)
        )
        session = self.client.session
        session["member_id"] = self.bob.pk
        session.save()
        self.note(author=self.ada, minutes_ago=5)
        self.note(author=self.ada, minutes_ago=10 * 24 * 60)

        response = self.home()

        self.assertContains(response, "1 new note")
        self.assertNotContains(response, "2 new notes")

    def test_query_count_does_not_grow_with_notes(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        top = self.note()
        with CaptureQueriesContext(connection) as one:
            self.home()
        for _ in range(10):
            self.note()
        for _ in range(9):
            self.note(parent=top)
        with CaptureQueriesContext(connection) as many:
            self.home()

        self.assertEqual(len(one), len(many))
        self.assertEqual(len(many), HOME_QUERIES_WITH_PANEL)

    def test_mark_seen_clears_notes_and_replies(self):
        top = self.note()
        self.note(parent=top)
        self.assertContains(self.home(), PANEL)

        self.client.post(reverse("club:mark_seen"))

        self.assertNotContains(self.home(), PANEL)


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
