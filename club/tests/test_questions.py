"""Admin-posted discussion questions: the model, the page, and the gate."""

from django.test import TestCase
from django.urls import reverse

from ..models import Book, Member, Question


class QuestionModelTests(TestCase):
    """The row, and the order the admin chose for it."""

    @classmethod
    def setUpTestData(cls):
        cls.book = Book.objects.create(title="Middlemarch", author="George Eliot")

    def test_questions_come_back_in_the_admins_order_not_by_age(self):
        """#12 is explicit that the sequence is a decision. A group's questions
        have a shape and it is rarely the order somebody typed them in."""
        last = Question.objects.create(book=self.book, text="Last", position=3)
        first = Question.objects.create(book=self.book, text="First", position=1)
        middle = Question.objects.create(book=self.book, text="Middle", position=2)

        self.assertEqual(list(self.book.questions.all()), [first, middle, last])

    def test_questions_sharing_a_position_fall_back_to_age(self):
        older = Question.objects.create(book=self.book, text="Older", position=1)
        newer = Question.objects.create(book=self.book, text="Newer", position=1)

        self.assertEqual(list(self.book.questions.all()), [older, newer])

    def test_a_question_belongs_to_a_book(self):
        """Decision #8, so #14 can replay a past book's discussion."""
        other = Book.objects.create(title="Piranesi", author="Susanna Clarke")
        Question.objects.create(book=self.book, text="Ours")
        Question.objects.create(book=other, text="Theirs")

        self.assertEqual(self.book.questions.count(), 1)

    def test_deleting_a_book_takes_its_questions(self):
        Question.objects.create(book=self.book, text="Ours")

        self.book.delete()

        self.assertEqual(Question.objects.count(), 0)

    def test_str_is_the_question_itself(self):
        question = Question(book=self.book, text="What did Dorothea want?")

        self.assertEqual(str(question), "What did Dorothea want?")


class QuestionsPageTests(TestCase):
    """Reading the page, which is open to anyone."""

    @classmethod
    def setUpTestData(cls):
        cls.book = Book.objects.create(
            title="Middlemarch", author="George Eliot", is_current=True
        )
        cls.question = Question.objects.create(
            book=cls.book, text="What did Dorothea want?", position=1
        )

    def test_anyone_can_read_the_questions(self):
        response = self.client.get(reverse("club:questions"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "What did Dorothea want?")
        self.assertContains(response, "Middlemarch")

    def test_questions_on_another_book_do_not_appear(self):
        other = Book.objects.create(title="Piranesi", author="Susanna Clarke")
        Question.objects.create(book=other, text="Who is the Other?")

        response = self.client.get(reverse("club:questions"))

        self.assertNotContains(response, "Who is the Other?")

    def test_a_non_admin_sees_no_edit_controls(self):
        response = self.client.get(reverse("club:questions"))

        self.assertNotContains(response, reverse("club:question_add"))
        self.assertNotContains(
            response, reverse("club:question_edit", args=[self.question.pk])
        )
        self.assertNotContains(
            response, reverse("club:question_delete", args=[self.question.pk])
        )

    def test_an_admin_sees_them(self):
        session = self.client.session
        session["is_club_admin"] = True
        session.save()

        response = self.client.get(reverse("club:questions"))

        self.assertContains(response, reverse("club:question_add"))
        self.assertContains(
            response, reverse("club:question_edit", args=[self.question.pk])
        )
        self.assertContains(
            response, reverse("club:question_delete", args=[self.question.pk])
        )

    def test_question_text_renders_escaped(self):
        Question.objects.create(book=self.book, text="<b>Bold</b> claim?", position=2)

        response = self.client.get(reverse("club:questions"))

        self.assertNotContains(response, "<b>Bold</b>")
        self.assertContains(response, "&lt;b&gt;Bold&lt;/b&gt;")

    def test_the_nav_reaches_the_questions(self):
        response = self.client.get(reverse("club:home"))

        self.assertContains(response, reverse("club:questions"))


class QuestionsEmptyStateTests(TestCase):
    """Both of the ways this page has nothing to show."""

    def test_no_current_book_says_so(self):
        response = self.client.get(reverse("club:questions"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No book in progress")

    def test_a_book_with_no_questions_says_who_can_fix_it(self):
        Book.objects.create(
            title="Middlemarch", author="George Eliot", is_current=True
        )

        response = self.client.get(reverse("club:questions"))

        self.assertContains(response, "No questions on Middlemarch yet")
        self.assertContains(response, "an admin can post the first one")


class QuestionGateTests(TestCase):
    """Hiding the controls is decoration. This is the enforcement."""

    @classmethod
    def setUpTestData(cls):
        cls.book = Book.objects.create(
            title="Middlemarch", author="George Eliot", is_current=True
        )
        cls.question = Question.objects.create(
            book=cls.book, text="What did Dorothea want?", position=1
        )

    def test_a_non_admin_post_to_add_is_refused(self):
        response = self.client.post(
            reverse("club:question_add"), {"text": "Mine now", "position": "1"}
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Question.objects.count(), 1)

    def test_a_non_admin_post_to_edit_is_refused(self):
        response = self.client.post(
            reverse("club:question_edit", args=[self.question.pk]),
            {"text": "Reworded", "position": "1"},
        )

        self.assertEqual(response.status_code, 403)
        self.question.refresh_from_db()
        self.assertEqual(self.question.text, "What did Dorothea want?")

    def test_a_non_admin_post_to_delete_is_refused(self):
        response = self.client.post(
            reverse("club:question_delete", args=[self.question.pk])
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Question.objects.count(), 1)

    def test_a_non_admin_get_asks_for_the_pin_and_comes_back(self):
        for url in (
            reverse("club:question_add"),
            reverse("club:question_edit", args=[self.question.pk]),
            reverse("club:question_delete", args=[self.question.pk]),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertEqual(response.status_code, 302)
                self.assertTrue(
                    response["Location"].startswith(reverse("club:admin_pin"))
                )

    def test_an_identified_member_is_still_not_an_admin(self):
        """Decision #16: the two session keys are unrelated."""
        ada = Member.objects.create(name="Ada")
        session = self.client.session
        session["member_id"] = ada.pk
        session.save()

        response = self.client.post(
            reverse("club:question_add"), {"text": "Mine now", "position": "1"}
        )

        self.assertEqual(response.status_code, 403)


class QuestionAdminActionsTests(TestCase):
    """What an admin can do once the PIN is in the session."""

    @classmethod
    def setUpTestData(cls):
        cls.book = Book.objects.create(
            title="Middlemarch", author="George Eliot", is_current=True
        )

    def setUp(self):
        session = self.client.session
        session["is_club_admin"] = True
        session.save()

    def test_an_admin_can_post_a_question(self):
        response = self.client.post(
            reverse("club:question_add"),
            {"text": "What did Dorothea want?", "position": "1"},
            follow=True,
        )

        self.assertRedirects(response, reverse("club:questions"))
        question = Question.objects.get()
        self.assertEqual(question.book, self.book)
        self.assertEqual(question.position, 1)
        self.assertContains(response, "Question posted.")

    def test_the_add_form_suggests_the_next_position(self):
        """So the common case — one more at the end — needs no arithmetic."""
        Question.objects.create(book=self.book, text="First", position=1)
        Question.objects.create(book=self.book, text="Second", position=2)

        response = self.client.get(reverse("club:question_add"))

        self.assertEqual(response.context["form"].initial["position"], 3)

    def test_the_first_question_is_suggested_position_one(self):
        response = self.client.get(reverse("club:question_add"))

        self.assertEqual(response.context["form"].initial["position"], 1)

    def test_the_form_carries_no_book_field(self):
        response = self.client.get(reverse("club:question_add"))

        self.assertEqual(list(response.context["form"].fields), ["text", "position"])

    def test_a_submitted_book_is_ignored(self):
        other = Book.objects.create(title="Piranesi", author="Susanna Clarke")

        self.client.post(
            reverse("club:question_add"),
            {"text": "Mine", "position": "1", "book": other.pk},
        )

        self.assertEqual(Question.objects.get().book, self.book)

    def test_an_empty_question_is_a_form_error(self):
        response = self.client.post(
            reverse("club:question_add"), {"text": "   ", "position": "1"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"], "text", "A question needs something in it."
        )
        self.assertEqual(Question.objects.count(), 0)

    def test_an_admin_can_reword_a_question(self):
        question = Question.objects.create(book=self.book, text="Old", position=1)

        response = self.client.post(
            reverse("club:question_edit", args=[question.pk]),
            {"text": "New wording", "position": "1"},
        )

        self.assertRedirects(response, reverse("club:questions"))
        question.refresh_from_db()
        self.assertEqual(question.text, "New wording")

    def test_an_admin_reorders_by_changing_the_position(self):
        first = Question.objects.create(book=self.book, text="First", position=1)
        second = Question.objects.create(book=self.book, text="Second", position=2)

        self.client.post(
            reverse("club:question_edit", args=[second.pk]),
            {"text": "Second", "position": "0"},
        )

        self.assertEqual(list(self.book.questions.all()), [second, first])

    def test_adding_a_question_with_no_current_book_is_refused(self):
        self.book.is_current = False
        self.book.save(update_fields=["is_current"])

        response = self.client.post(
            reverse("club:question_add"), {"text": "Nowhere", "position": "1"},
            follow=True,
        )

        self.assertRedirects(response, reverse("club:home"))
        self.assertContains(response, "There is no current book")
        self.assertEqual(Question.objects.count(), 0)


class QuestionDeleteTests(TestCase):
    """Removing a question, and saying what goes with it."""

    @classmethod
    def setUpTestData(cls):
        cls.book = Book.objects.create(
            title="Middlemarch", author="George Eliot", is_current=True
        )

    def setUp(self):
        self.question = Question.objects.create(
            book=self.book, text="What did Dorothea want?", position=1
        )
        self.url = reverse("club:question_delete", args=[self.question.pk])
        session = self.client.session
        session["is_club_admin"] = True
        session.save()

    def test_the_confirmation_warns_that_the_answers_go_too(self):
        """The answers are other people's writing, and the admin cannot see
        them from the button."""
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "What did Dorothea want?")
        self.assertContains(response, "also removes every answer")

    def test_the_confirmation_deletes_nothing(self):
        self.client.get(self.url)

        self.assertEqual(Question.objects.count(), 1)

    def test_a_post_removes_it(self):
        response = self.client.post(self.url, follow=True)

        self.assertRedirects(response, reverse("club:questions"))
        self.assertEqual(Question.objects.count(), 0)
        self.assertContains(response, "Question removed, along with its answers.")

    def test_removing_a_question_that_is_not_there_is_a_404(self):
        response = self.client.post(reverse("club:question_delete", args=[9999]))

        self.assertEqual(response.status_code, 404)
