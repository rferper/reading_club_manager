"""Free-text notes on the current book: posting, reading, removing."""

from datetime import date

from django.db.models import ProtectedError
from django.test import TestCase
from django.urls import reverse

from ..models import Book, Member, Note


class NoteModelTests(TestCase):
    """The row, and what it refuses to let go of."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.book = Book.objects.create(title="Middlemarch", author="George Eliot")

    def test_notes_come_back_newest_first(self):
        first = Note.objects.create(book=self.book, author=self.ada, body="One")
        second = Note.objects.create(book=self.book, author=self.ada, body="Two")

        self.assertEqual(list(self.book.notes.all()), [second, first])

    def test_a_note_belongs_to_a_book_and_not_to_whatever_is_current(self):
        """Decision #8: the archive replays a finished book's discussion, which
        needs the note tied to that book rather than to the moment."""
        note = Note.objects.create(book=self.book, author=self.ada, body="One")

        self.book.is_current = True
        self.book.save(update_fields=["is_current"])

        self.assertEqual(note.book, self.book)

    def test_a_member_with_notes_cannot_be_deleted(self):
        """Decision #3: a member who leaves the club leaves the roster, not the
        record. The admin already refuses; this is the lock in the schema, which
        a fixture or a shell would otherwise walk past."""
        Note.objects.create(book=self.book, author=self.ada, body="One")

        with self.assertRaises(ProtectedError):
            self.ada.delete()

    def test_deleting_a_book_takes_its_notes(self):
        """The other direction is a cascade: a book's discussion is about that
        book and means nothing without it."""
        Note.objects.create(book=self.book, author=self.ada, body="One")

        self.book.delete()

        self.assertEqual(Note.objects.count(), 0)


class NotePermissionTests(TestCase):
    """Who may remove a note, asked of the model."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.bob = Member.objects.create(name="Bob")
        cls.book = Book.objects.create(title="Middlemarch", author="George Eliot")
        cls.note = Note.objects.create(book=cls.book, author=cls.ada, body="One")

    def test_the_author_may(self):
        self.assertIs(self.note.may_be_removed_by(self.ada, False), True)

    def test_another_member_may_not(self):
        self.assertIs(self.note.may_be_removed_by(self.bob, False), False)

    def test_an_admin_may(self):
        self.assertIs(self.note.may_be_removed_by(self.bob, True), True)

    def test_a_stranger_may_not(self):
        self.assertIs(self.note.may_be_removed_by(None, False), False)

    def test_an_unidentified_admin_may(self):
        """The PIN is not a claim about who you are — decision #16 keeps the
        two session keys unrelated in both directions."""
        self.assertIs(self.note.may_be_removed_by(None, True), True)


class NotesPageTests(TestCase):
    """Reading the page, which is open to anyone."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.book = Book.objects.create(
            title="Middlemarch",
            author="George Eliot",
            started_on=date(2025, 9, 1),
            is_current=True,
        )

    def test_the_page_lists_the_current_books_notes(self):
        Note.objects.create(book=self.book, author=self.ada, body="Dorothea, again.")

        response = self.client.get(reverse("club:notes"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dorothea, again.")
        self.assertContains(response, "Ada")

    def test_notes_on_another_book_do_not_appear(self):
        other = Book.objects.create(title="Piranesi", author="Susanna Clarke")
        Note.objects.create(book=other, author=self.ada, body="The statues.")

        response = self.client.get(reverse("club:notes"))

        self.assertNotContains(response, "The statues.")

    def test_a_note_from_a_since_deactivated_member_keeps_their_name(self):
        """The whole reason members are deactivated rather than deleted."""
        Note.objects.create(book=self.book, author=self.ada, body="Dorothea, again.")
        self.ada.is_active = False
        self.ada.save(update_fields=["is_active"])

        response = self.client.get(reverse("club:notes"))

        self.assertContains(response, "Dorothea, again.")
        self.assertContains(response, "Ada")

    def test_a_book_with_no_notes_says_so(self):
        response = self.client.get(reverse("club:notes"))

        self.assertContains(response, "No notes on Middlemarch yet")

    def test_a_stranger_is_asked_who_they_are_before_the_form(self):
        response = self.client.get(reverse("club:notes"))

        self.assertContains(response, "Say who you are")
        self.assertNotContains(response, "Post note")

    def test_an_identified_member_gets_the_form(self):
        session = self.client.session
        session["member_id"] = self.ada.pk
        session.save()

        response = self.client.get(reverse("club:notes"))

        self.assertContains(response, "Post note")
        self.assertContains(response, 'for="id_body"')

    def test_the_nav_reaches_the_notes(self):
        response = self.client.get(reverse("club:home"))

        self.assertContains(response, reverse("club:notes"))


class NoNotesBookTests(TestCase):
    """Between reads there is no book for a note to belong to."""

    def test_the_page_says_so_and_offers_no_form(self):
        response = self.client.get(reverse("club:notes"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No book in progress")
        self.assertNotContains(response, "Post note")

    def test_a_post_is_refused_and_stores_nothing(self):
        ada = Member.objects.create(name="Ada")
        session = self.client.session
        session["member_id"] = ada.pk
        session.save()

        response = self.client.post(
            reverse("club:notes"), {"body": "Anywhere"}, follow=True
        )

        self.assertRedirects(response, reverse("club:home"))
        self.assertContains(response, "There is no current book")
        self.assertEqual(Note.objects.count(), 0)


class PostNoteTests(TestCase):
    """Adding a note as the session's member."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.book = Book.objects.create(
            title="Middlemarch", author="George Eliot", is_current=True
        )

    def setUp(self):
        session = self.client.session
        session["member_id"] = self.ada.pk
        session.save()

    def test_a_note_is_attributed_to_the_session_member(self):
        response = self.client.post(
            reverse("club:notes"), {"body": "Dorothea, again."}, follow=True
        )

        self.assertRedirects(response, reverse("club:notes"))
        note = Note.objects.get()
        self.assertEqual(note.author, self.ada)
        self.assertEqual(note.book, self.book)
        self.assertContains(response, "Note posted.")

    def test_the_form_carries_no_author_or_book_field(self):
        response = self.client.get(reverse("club:notes"))

        self.assertEqual(list(response.context["form"].fields), ["body"])

    def test_a_submitted_author_is_ignored(self):
        bob = Member.objects.create(name="Bob")

        self.client.post(
            reverse("club:notes"), {"body": "Not from Bob", "author": bob.pk}
        )

        self.assertEqual(Note.objects.get().author, self.ada)

    def test_an_empty_body_is_a_form_error(self):
        response = self.client.post(reverse("club:notes"), {"body": ""})

        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"], "body", "A note needs something in it."
        )
        self.assertEqual(Note.objects.count(), 0)

    def test_a_whitespace_only_body_is_a_form_error(self):
        """Django strips the field, so "   " arrives as "" and fails
        `required` without a check of its own."""
        response = self.client.post(reverse("club:notes"), {"body": "   \n\t  "})

        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"], "body", "A note needs something in it."
        )
        self.assertEqual(Note.objects.count(), 0)

    def test_an_unidentified_post_is_refused_rather_than_redirected(self):
        """Decision #16: a redirect would answer the POST with a GET and lose
        what the member typed."""
        self.client.session.flush()
        fresh = self.client_class()

        response = fresh.post(reverse("club:notes"), {"body": "From nobody"})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Note.objects.count(), 0)

    def test_posting_twice_makes_two_notes(self):
        """Unlike progress and answers, a note is a reaction, not a standing
        position — two of them is a conversation, not a duplicate."""
        self.client.post(reverse("club:notes"), {"body": "One"})
        self.client.post(reverse("club:notes"), {"body": "Two"})

        self.assertEqual(Note.objects.count(), 2)


class NoteRenderingTests(TestCase):
    """What a body turns into on the way to the page."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.book = Book.objects.create(
            title="Middlemarch", author="George Eliot", is_current=True
        )

    def test_a_body_containing_markup_renders_as_text(self):
        Note.objects.create(
            book=self.book,
            author=self.ada,
            body="<script>alert('hi')</script> is not a plot point",
        )

        response = self.client.get(reverse("club:notes"))

        self.assertNotContains(response, "<script>alert")
        self.assertContains(response, "&lt;script&gt;")
        self.assertContains(response, "is not a plot point")

    def test_line_breaks_are_preserved(self):
        Note.objects.create(
            book=self.book, author=self.ada, body="First line\nSecond line"
        )

        response = self.client.get(reverse("club:notes"))

        self.assertContains(response, "First line<br>Second line")

    def test_a_blank_line_starts_a_new_paragraph(self):
        Note.objects.create(
            book=self.book, author=self.ada, body="First para\n\nSecond para"
        )

        response = self.client.get(reverse("club:notes"))

        self.assertContains(response, "<p>First para</p>")
        self.assertContains(response, "<p>Second para</p>")


class NoteDeleteTests(TestCase):
    """Removing a note, which is a POST and a real refusal when it is not yours."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.bob = Member.objects.create(name="Bob")
        cls.book = Book.objects.create(
            title="Middlemarch", author="George Eliot", is_current=True
        )

    def setUp(self):
        self.note = Note.objects.create(
            book=self.book, author=self.ada, body="Dorothea, again."
        )
        self.url = reverse("club:note_delete", args=[self.note.pk])

    def _identify(self, member):
        session = self.client.session
        session["member_id"] = member.pk
        session.save()

    def test_the_author_can_remove_their_own_note(self):
        self._identify(self.ada)

        response = self.client.post(self.url, follow=True)

        self.assertRedirects(response, reverse("club:notes"))
        self.assertEqual(Note.objects.count(), 0)
        self.assertContains(response, "Note removed.")

    def test_an_admin_can_remove_anybody_s_note(self):
        session = self.client.session
        session["is_club_admin"] = True
        session.save()

        self.client.post(self.url)

        self.assertEqual(Note.objects.count(), 0)

    def test_another_member_is_refused_with_a_403(self):
        """Not a redirect: a member acting on somebody else's note is a real
        refusal, not a step they forgot to take."""
        self._identify(self.bob)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Note.objects.count(), 1)

    def test_a_stranger_is_refused_with_a_403(self):
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Note.objects.count(), 1)

    def test_a_get_never_deletes(self):
        self._identify(self.ada)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 405)
        self.assertEqual(Note.objects.count(), 1)

    def test_the_button_is_only_offered_to_someone_who_may_use_it(self):
        self._identify(self.bob)
        response = self.client.get(reverse("club:notes"))
        self.assertNotContains(response, self.url)

        self._identify(self.ada)
        response = self.client.get(reverse("club:notes"))
        self.assertContains(response, self.url)

    def test_removing_a_note_that_is_not_there_is_a_404(self):
        self._identify(self.ada)

        response = self.client.post(reverse("club:note_delete", args=[9999]))

        self.assertEqual(response.status_code, 404)
