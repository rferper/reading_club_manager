"""Members answering discussion questions, one standing answer each."""

from datetime import date

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase
from django.urls import reverse

from ..models import Answer, Book, Member, Question


class AnswerModelTests(TestCase):
    """One row per member per question, and the database says so."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.book = Book.objects.create(title="Middlemarch", author="George Eliot")
        cls.question = Question.objects.create(
            book=cls.book, text="What did Dorothea want?"
        )

    def test_a_second_answer_from_the_same_member_is_rejected(self):
        Answer.objects.create(question=self.question, member=self.ada, body="One")

        with self.assertRaises(IntegrityError), transaction.atomic():
            Answer.objects.create(question=self.question, member=self.ada, body="Two")

    def test_a_duplicate_is_a_validation_error_before_that(self):
        Answer.objects.create(question=self.question, member=self.ada, body="One")

        with self.assertRaises(ValidationError):
            Answer(question=self.question, member=self.ada, body="Two").full_clean()

    def test_two_members_may_answer_the_same_question(self):
        bob = Member.objects.create(name="Bob")
        Answer.objects.create(question=self.question, member=self.ada, body="Hers")
        Answer.objects.create(question=self.question, member=bob, body="His")

        self.assertEqual(self.question.answers.count(), 2)

    def test_one_member_may_answer_two_questions(self):
        second = Question.objects.create(book=self.book, text="And Lydgate?")
        Answer.objects.create(question=self.question, member=self.ada, body="One")
        Answer.objects.create(question=second, member=self.ada, body="Two")

        self.assertEqual(self.ada.answers.count(), 2)

    def test_answers_come_back_oldest_first(self):
        """The order the conversation happened in, which is what a reader of
        the archive wants."""
        bob = Member.objects.create(name="Bob")
        first = Answer.objects.create(
            question=self.question, member=self.ada, body="Hers"
        )
        second = Answer.objects.create(question=self.question, member=bob, body="His")

        self.assertEqual(list(self.question.answers.all()), [first, second])

    def test_removing_a_question_removes_its_answers(self):
        """Which is what the delete confirmation warns about."""
        Answer.objects.create(question=self.question, member=self.ada, body="One")

        self.question.delete()

        self.assertEqual(Answer.objects.count(), 0)

    def test_a_member_with_answers_cannot_be_deleted(self):
        """Decision #3 and #20: the member leaves the roster, not the record."""
        Answer.objects.create(question=self.question, member=self.ada, body="One")

        with self.assertRaises(ProtectedError):
            self.ada.delete()

    def test_a_fresh_answer_does_not_claim_to_have_been_edited(self):
        answer = Answer.objects.create(
            question=self.question, member=self.ada, body="One"
        )

        self.assertIs(answer.was_edited, False)


class AnswerUpdateInPlaceTests(TestCase):
    """The point of the issue: changing your mind is an update."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.book = Book.objects.create(
            title="Middlemarch", author="George Eliot", is_current=True
        )
        cls.question = Question.objects.create(
            book=cls.book, text="What did Dorothea want?", position=1
        )

    def setUp(self):
        session = self.client.session
        session["member_id"] = self.ada.pk
        session.save()

    def _answer(self, body):
        return self.client.post(
            reverse("club:questions"),
            {"question": self.question.pk, "body": body},
        )

    def test_answering_twice_replaces_rather_than_adds(self):
        self._answer("At first I thought reform.")
        self._answer("On reflection, to be useful.")

        self.assertEqual(Answer.objects.count(), 1)
        self.assertEqual(Answer.objects.get().body, "On reflection, to be useful.")

    def test_answering_twice_does_not_raise_an_integrity_error(self):
        """A uniqueness constraint without an update path is an integrity error
        waiting for the first person who changes their mind — decision #6."""
        self._answer("First")

        response = self._answer("Second")

        self.assertRedirects(response, reverse("club:questions"))

    def test_the_second_answer_keeps_the_first_ones_creation_time(self):
        self._answer("First")
        created = Answer.objects.get().created_on

        self._answer("Second")

        self.assertEqual(Answer.objects.get().created_on, created)

    def test_two_members_editing_do_not_collide(self):
        bob = Member.objects.create(name="Bob")
        self._answer("Hers")

        session = self.client.session
        session["member_id"] = bob.pk
        session.save()
        self._answer("His")
        self._answer("His, revised")

        self.assertEqual(Answer.objects.count(), 2)
        self.assertEqual(Answer.objects.get(member=bob).body, "His, revised")
        self.assertEqual(Answer.objects.get(member=self.ada).body, "Hers")


class AnswersOnThePageTests(TestCase):
    """What the questions page shows once there are answers."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.bob = Member.objects.create(name="Bob")
        cls.book = Book.objects.create(
            title="Middlemarch", author="George Eliot", is_current=True
        )
        cls.question = Question.objects.create(
            book=cls.book, text="What did Dorothea want?", position=1
        )
        Answer.objects.create(
            question=cls.question, member=cls.ada, body="To be useful."
        )
        Answer.objects.create(question=cls.question, member=cls.bob, body="Reform.")

    def test_every_answer_shows_under_its_question_with_a_name(self):
        response = self.client.get(reverse("club:questions"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "To be useful.")
        self.assertContains(response, "Reform.")
        self.assertContains(response, "Ada")
        self.assertContains(response, "Bob")

    def test_a_stranger_can_read_them_but_is_offered_no_form(self):
        response = self.client.get(reverse("club:questions"))

        self.assertContains(response, "To be useful.")
        self.assertContains(response, "Say who you are")
        self.assertNotContains(response, "Post answer")

    def test_a_member_who_has_not_answered_sees_a_form(self):
        cleo = Member.objects.create(name="Cleo")
        session = self.client.session
        session["member_id"] = cleo.pk
        session.save()

        response = self.client.get(reverse("club:questions"))

        self.assertContains(response, "Post answer")
        self.assertIsNone(response.context["rows"][0]["mine"])

    def test_a_member_who_has_answered_sees_an_edit_affordance(self):
        session = self.client.session
        session["member_id"] = self.ada.pk
        session.save()

        response = self.client.get(reverse("club:questions"))

        self.assertContains(response, "Edit your answer")
        self.assertNotContains(response, "Post answer")
        self.assertEqual(response.context["rows"][0]["mine"].body, "To be useful.")

    def test_the_edit_form_starts_from_what_they_wrote(self):
        session = self.client.session
        session["member_id"] = self.ada.pk
        session.save()

        response = self.client.get(reverse("club:questions"))

        self.assertEqual(
            response.context["rows"][0]["form"].initial["body"], "To be useful."
        )

    def test_a_question_with_no_answers_says_so(self):
        Question.objects.create(book=self.book, text="And Lydgate?", position=2)

        response = self.client.get(reverse("club:questions"))

        self.assertContains(response, "Nobody has answered this one yet.")

    def test_a_body_containing_markup_renders_as_text(self):
        Answer.objects.get(member=self.bob).delete()
        Answer.objects.create(
            question=self.question,
            member=self.bob,
            body="<script>alert('hi')</script>",
        )

        response = self.client.get(reverse("club:questions"))

        self.assertNotContains(response, "<script>alert")
        self.assertContains(response, "&lt;script&gt;")

    def test_line_breaks_are_preserved(self):
        Answer.objects.filter(member=self.ada).update(body="First line\nSecond line")

        response = self.client.get(reverse("club:questions"))

        self.assertContains(response, "First line<br>Second line")

    def test_an_answer_from_a_since_deactivated_member_keeps_their_name(self):
        self.ada.is_active = False
        self.ada.save(update_fields=["is_active"])

        response = self.client.get(reverse("club:questions"))

        self.assertContains(response, "To be useful.")
        self.assertContains(response, "Ada")

    def test_the_page_does_not_query_once_per_question(self):
        for index in range(2, 8):
            question = Question.objects.create(
                book=self.book, text=f"Question {index}", position=index
            )
            Answer.objects.create(question=question, member=self.ada, body="Yes")

        with self.assertNumQueries(3):
            response = self.client.get(reverse("club:questions"))

        self.assertEqual(len(response.context["rows"]), 7)

    def test_rendering_seven_forms_does_not_query_seven_times(self):
        """Every question carries a form whose hidden `question` field is a
        `ModelChoiceField`. One shared queryset, evaluated never — a hidden
        input renders no choices."""
        for index in range(2, 8):
            Question.objects.create(
                book=self.book, text=f"Question {index}", position=index
            )
        session = self.client.session
        session["member_id"] = self.ada.pk
        session.save()

        # Five: the session, the current book, the viewer's member row, the
        # questions, and one prefetch for all of their answers.
        with self.assertNumQueries(5):
            response = self.client.get(reverse("club:questions"))

        self.assertEqual(len(response.context["rows"]), 7)
        self.assertContains(response, "Post answer")


class AnswerRefusalTests(TestCase):
    """What is not answerable, and what happens when somebody tries."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.book = Book.objects.create(
            title="Middlemarch", author="George Eliot", is_current=True
        )
        cls.question = Question.objects.create(
            book=cls.book, text="What did Dorothea want?", position=1
        )
        cls.finished = Book.objects.create(
            title="Piranesi", author="Susanna Clarke", finished_on=date(2025, 1, 1)
        )
        cls.old_question = Question.objects.create(
            book=cls.finished, text="Who is the Other?", position=1
        )

    def _identify(self):
        session = self.client.session
        session["member_id"] = self.ada.pk
        session.save()

    def test_a_question_on_a_finished_book_cannot_be_answered(self):
        """The URL exists and the question is real; the book is closed."""
        self._identify()

        response = self.client.post(
            reverse("club:questions"),
            {"question": self.old_question.pk, "body": "Too late"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Answer.objects.count(), 0)

    def test_a_question_id_that_is_not_a_number_is_a_form_error_not_a_500(self):
        self._identify()

        response = self.client.post(
            reverse("club:questions"), {"question": "nonsense", "body": "Hello"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Answer.objects.count(), 0)

    def test_a_missing_question_id_is_a_form_error(self):
        self._identify()

        response = self.client.post(reverse("club:questions"), {"body": "Hello"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Answer.objects.count(), 0)

    def test_an_empty_answer_is_a_form_error_on_that_question(self):
        self._identify()

        response = self.client.post(
            reverse("club:questions"), {"question": self.question.pk, "body": "   "}
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "An answer needs something in it.")
        self.assertEqual(Answer.objects.count(), 0)

    def test_a_failed_answer_reopens_only_its_own_form(self):
        """The other questions keep their fresh forms, so one mistake does not
        blank what the member typed everywhere else."""
        second = Question.objects.create(book=self.book, text="And Lydgate?", position=2)
        self._identify()

        response = self.client.post(
            reverse("club:questions"), {"question": self.question.pk, "body": ""}
        )

        rows = {row["question"].pk: row for row in response.context["rows"]}
        self.assertTrue(rows[self.question.pk]["form"].errors)
        self.assertFalse(rows[second.pk]["form"].errors)

    def test_an_unidentified_post_is_refused_rather_than_redirected(self):
        """Decision #16 again: a redirect would drop what they typed."""
        response = self.client.post(
            reverse("club:questions"),
            {"question": self.question.pk, "body": "From nobody"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Answer.objects.count(), 0)

    def test_a_submitted_member_field_is_ignored(self):
        bob = Member.objects.create(name="Bob")
        self._identify()

        self.client.post(
            reverse("club:questions"),
            {"question": self.question.pk, "body": "Mine", "member": bob.pk},
        )

        self.assertEqual(Answer.objects.get().member, self.ada)

    def test_answering_with_no_current_book_is_refused(self):
        self.book.is_current = False
        self.book.save(update_fields=["is_current"])
        self._identify()

        response = self.client.post(
            reverse("club:questions"),
            {"question": self.question.pk, "body": "Nowhere"},
            follow=True,
        )

        self.assertRedirects(response, reverse("club:home"))
        self.assertContains(response, "There is no current book")
        self.assertEqual(Answer.objects.count(), 0)
