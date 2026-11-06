"""Chapter anchors on notes and questions, and the notes page's ?chapter= filter."""

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .helpers import enter_admin
from ..models import Book, Member, Note, Question


class ChapterTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.book = Book.objects.create(
            title="Middlemarch",
            author="George Eliot",
            total_chapters=20,
            is_current=True,
        )

    def identify(self, member=None, admin=False):
        session = self.client.session
        if member is not None:
            session["member_id"] = member.pk
        if admin:
            enter_admin(session)
        session.save()

    def post_note(self, **data):
        data.setdefault("body", "A thought")
        return self.client.post(reverse("club:notes"), data)


class NoteChapterPostTests(ChapterTestBase):
    def setUp(self):
        self.identify(self.ada)

    def test_a_note_with_a_chapter_saves_and_shows_its_label(self):
        self.post_note(chapter="12")

        self.assertEqual(Note.objects.get().chapter, 12)
        self.assertContains(self.client.get(reverse("club:notes")), "Chapter 12")

    def test_a_blank_chapter_saves_an_unanchored_note(self):
        self.post_note(chapter="")

        self.assertIsNone(Note.objects.get().chapter)
        self.assertNotContains(self.client.get(reverse("club:notes")), "Chapter ")

    def test_an_omitted_chapter_saves_an_unanchored_note(self):
        self.post_note()

        self.assertIsNone(Note.objects.get().chapter)

    def test_chapter_zero_is_refused(self):
        response = self.post_note(chapter="0")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors["chapter"])
        self.assertEqual(Note.objects.count(), 0)

    def test_bad_chapters_are_refused(self):
        for bad in ("-3", "2.5", "2.0", "abc"):
            with self.subTest(bad=bad):
                response = self.post_note(chapter=bad)

                self.assertTrue(response.context["form"].errors["chapter"])

        self.assertEqual(Note.objects.count(), 0)

    def test_a_chapter_above_the_total_is_refused_and_names_the_maximum(self):
        response = self.post_note(chapter="21")

        self.assertContains(response, "at most 20")
        self.assertEqual(Note.objects.count(), 0)

    def test_the_last_chapter_is_accepted(self):
        self.post_note(chapter="20")

        self.assertEqual(Note.objects.get().chapter, 20)

    def test_a_book_without_a_chapter_count_accepts_any_positive_chapter(self):
        Book.objects.filter(pk=self.book.pk).update(
            total_chapters=None, total_pages=300
        )

        self.post_note(chapter="400")

        self.assertEqual(Note.objects.get().chapter, 400)

    def test_an_unidentified_post_is_still_refused(self):
        anon = self.client_class()
        result = anon.post(reverse("club:notes"), {"body": "Hi", "chapter": "3"})

        self.assertEqual(result.status_code, 403)
        self.assertEqual(Note.objects.count(), 0)


class ReplyChapterTests(ChapterTestBase):
    def test_a_reply_stores_no_chapter_and_has_no_chapter_field(self):
        top = Note.objects.create(
            book=self.book, author=self.ada, body="Top", chapter=4
        )
        self.identify(self.ada)

        response = self.client.get(reverse("club:notes"))
        self.assertEqual(
            list(response.context["rows"][0]["reply_form"].fields), ["body", "parent"]
        )

        self.client.post(
            reverse("club:notes"), {"parent": top.pk, "body": "Re", "chapter": "9"}
        )

        self.assertIsNone(Note.objects.get(parent=top).chapter)


class NoteChapterFilterTests(ChapterTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.plain = Note.objects.create(book=cls.book, author=cls.ada, body="Plain one")
        cls.c3 = Note.objects.create(
            book=cls.book, author=cls.ada, body="Three one", chapter=3
        )
        cls.c5 = Note.objects.create(
            book=cls.book, author=cls.ada, body="Five one", chapter=5
        )
        cls.c3_later = Note.objects.create(
            book=cls.book, author=cls.ada, body="Three two", chapter=3
        )
        cls.reply = Note.objects.create(
            book=cls.book, author=cls.ada, body="Reply to three", parent=cls.c3
        )

    def notes(self, query=""):
        return self.client.get(reverse("club:notes") + query)

    def test_the_filter_lists_only_that_chapter_with_replies(self):
        response = self.notes("?chapter=3")

        self.assertEqual(
            [r["note"] for r in response.context["rows"]], [self.c3_later, self.c3]
        )
        self.assertContains(response, "Reply to three")
        self.assertNotContains(response, "Five one")
        self.assertNotContains(response, "Plain one")

    def test_the_filter_says_so_and_links_back_to_everything(self):
        response = self.notes("?chapter=3")

        self.assertContains(response, "Showing only notes on chapter 3")
        self.assertContains(response, f'href="{reverse("club:notes")}"')

    def test_a_chapter_with_no_notes_names_the_chapter(self):
        response = self.notes("?chapter=9")

        self.assertEqual(response.context["rows"], [])
        self.assertContains(response, "No notes on chapter 9")

    def test_junk_values_are_ignored(self):
        for junk in ("", "abc", "2.5", "0", "-1", "3x"):
            with self.subTest(junk=junk):
                response = self.notes(f"?chapter={junk}")

                self.assertEqual(len(response.context["rows"]), 4)
                self.assertNotContains(response, "Showing only")

    def test_an_absurdly_long_number_is_ignored_not_a_server_error(self):
        # More than 4300 digits makes int() raise; the page must not 500.
        for digits in ("9" * 10, "9" * 30, "9" * 5000):
            with self.subTest(length=len(digits)):
                response = self.notes(f"?chapter={digits}")

                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(response.context["rows"]), 4)
                self.assertNotContains(response, "Showing only")

    def test_the_unfiltered_list_includes_unanchored_notes(self):
        self.assertEqual(len(self.notes().context["rows"]), 4)

    def test_the_filter_changes_nothing(self):
        before = Note.objects.count()
        self.notes("?chapter=3")

        self.assertEqual(Note.objects.count(), before)

    def test_query_count_does_not_grow_with_notes_or_chapters(self):
        with CaptureQueriesContext(connection) as small:
            self.notes()

        for i in range(6):
            top = Note.objects.create(
                book=self.book, author=self.ada, body=f"n{i}", chapter=i + 1
            )
            Note.objects.create(
                book=self.book, author=self.ada, body=f"r{i}", parent=top
            )

        with CaptureQueriesContext(connection) as large:
            self.notes()

        with CaptureQueriesContext(connection) as filtered:
            self.notes("?chapter=3")

        self.assertEqual(len(small), len(large))
        self.assertEqual(len(small), len(filtered))


class QuestionChapterTests(ChapterTestBase):
    def setUp(self):
        self.identify(admin=True)

    def add(self, **extra):
        data = {"text": "Why?", "position": "1", **extra}
        return self.client.post(reverse("club:question_add"), data)

    def test_an_admin_can_anchor_a_question_and_it_shows(self):
        self.add(chapter="7")

        self.assertEqual(Question.objects.get().chapter, 7)
        self.assertContains(self.client.get(reverse("club:questions")), "Chapter 7")

    def test_an_admin_can_change_and_clear_it(self):
        question = Question.objects.create(book=self.book, text="Why?", chapter=2)
        url = reverse("club:question_edit", args=[question.pk])

        self.client.post(url, {"text": "Why?", "position": "1", "chapter": "8"})
        question.refresh_from_db()
        self.assertEqual(question.chapter, 8)

        self.client.post(url, {"text": "Why?", "position": "1", "chapter": ""})
        question.refresh_from_db()
        self.assertIsNone(question.chapter)

    def test_zero_and_over_total_are_refused_on_add_and_edit(self):
        question = Question.objects.create(book=self.book, text="Why?")
        edit = reverse("club:question_edit", args=[question.pk])

        for bad in ("0", "21", "1.5", "x"):
            with self.subTest(bad=bad):
                self.assertTrue(self.add(chapter=bad).context["form"].errors["chapter"])
                response = self.client.post(
                    edit, {"text": "Why?", "position": "1", "chapter": bad}
                )
                self.assertTrue(response.context["form"].errors["chapter"])

        self.assertEqual(Question.objects.count(), 1)
        question.refresh_from_db()
        self.assertIsNone(question.chapter)

    def test_a_non_admin_cannot_post_a_chapter_to_add_or_edit(self):
        question = Question.objects.create(book=self.book, text="Why?")
        anon = self.client_class()

        added = anon.post(
            reverse("club:question_add"),
            {"text": "Mine", "position": "1", "chapter": "3"},
        )
        edited = anon.post(
            reverse("club:question_edit", args=[question.pk]),
            {"text": "Mine", "position": "1", "chapter": "3"},
        )

        self.assertEqual(added.status_code, 403)
        self.assertEqual(edited.status_code, 403)
        self.assertEqual(Question.objects.count(), 1)
        question.refresh_from_db()
        self.assertIsNone(question.chapter)


class HistoryChapterTests(ChapterTestBase):
    def test_history_detail_shows_both_labels(self):
        Note.objects.create(book=self.book, author=self.ada, body="n", chapter=11)
        Question.objects.create(book=self.book, text="q", chapter=6)
        Book.objects.filter(pk=self.book.pk).update(is_current=False)

        response = self.client.get(reverse("club:history_detail", args=[self.book.pk]))

        self.assertContains(response, "Chapter 11")
        self.assertContains(response, "Chapter 6")

    def test_existing_style_rows_show_no_label(self):
        Note.objects.create(book=self.book, author=self.ada, body="n")
        Question.objects.create(book=self.book, text="q")
        Book.objects.filter(pk=self.book.pk).update(is_current=False)

        response = self.client.get(reverse("club:history_detail", args=[self.book.pk]))

        self.assertNotContains(response, "Chapter ")
