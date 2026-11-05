"""One level of replies on answers: the model, posting, display, removal."""

from datetime import date, timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from .helpers import enter_admin
from ..models import Answer, AnswerReply, Book, Member, Question


class AnswerReplyTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.bob = Member.objects.create(name="Bob")
        cls.book = Book.objects.create(
            title="Middlemarch", author="George Eliot", is_current=True
        )
        cls.old_book = Book.objects.create(
            title="Piranesi", author="Susanna Clarke", finished_on=date(2025, 1, 1)
        )
        cls.question = Question.objects.create(
            book=cls.book, text="What did Dorothea want?", position=1
        )
        cls.old_question = Question.objects.create(
            book=cls.old_book, text="Who is the Other?", position=1
        )
        cls.answer = Answer.objects.create(
            question=cls.question, member=cls.ada, body="To be useful."
        )
        cls.old_answer = Answer.objects.create(
            question=cls.old_question, member=cls.ada, body="A friend."
        )

    def identify(self, member, admin=False):
        session = self.client.session
        session["member_id"] = member.pk
        if admin:
            enter_admin(session)
        session.save()

    def reply_to(self, answer_id, body="A reply"):
        return self.client.post(
            reverse("club:questions"), {"answer": answer_id, "body": body}
        )

    def make_reply(self, answer=None, author=None, body="A reply", offset=0):
        reply = AnswerReply.objects.create(
            answer=answer or self.answer, author=author or self.bob, body=body
        )
        if offset:
            # Well-separated timestamps, so no same-tick ties decide the order.
            AnswerReply.objects.filter(pk=reply.pk).update(
                created_on=timezone.now() + timedelta(minutes=offset)
            )
        return reply


class AnswerReplyModelTests(AnswerReplyTestBase):
    def test_a_reply_is_reachable_from_its_answer(self):
        reply = self.make_reply()

        self.assertEqual(list(self.answer.replies.all()), [reply])
        self.assertEqual(list(self.bob.answer_replies.all()), [reply])

    def test_removing_a_question_removes_answers_and_replies(self):
        self.make_reply()

        self.question.delete()

        self.assertEqual(AnswerReply.objects.count(), 0)

    def test_removing_a_reply_leaves_the_answer(self):
        reply = self.make_reply()

        reply.delete()

        self.assertTrue(Answer.objects.filter(pk=self.answer.pk).exists())

    def test_editing_an_answer_keeps_its_replies(self):
        self.make_reply()
        self.identify(self.ada)

        self.client.post(
            reverse("club:questions"),
            {"question": self.question.pk, "body": "Revised."},
        )

        self.assertEqual(Answer.objects.get(pk=self.answer.pk).body, "Revised.")
        self.assertEqual(self.answer.replies.count(), 1)

    def test_author_and_admin_may_remove_others_may_not(self):
        reply = self.make_reply(author=self.bob)

        self.assertTrue(reply.may_be_removed_by(self.bob, False))
        self.assertTrue(reply.may_be_removed_by(self.ada, True))
        self.assertTrue(reply.may_be_removed_by(None, True))
        self.assertFalse(reply.may_be_removed_by(self.ada, False))
        self.assertFalse(reply.may_be_removed_by(None, False))


class AnswerReplyPostingTests(AnswerReplyTestBase):
    def test_a_member_sees_a_reply_form_under_an_answer(self):
        self.identify(self.bob)

        response = self.client.get(reverse("club:questions"))

        self.assertContains(response, ">Reply</button>")

    def test_a_stranger_sees_no_reply_form(self):
        response = self.client.get(reverse("club:questions"))

        self.assertContains(response, "To be useful.")
        self.assertNotContains(response, ">Reply</button>")

    def test_a_valid_reply_is_saved_and_redirects(self):
        self.identify(self.bob)

        response = self.reply_to(self.answer.pk, "I disagree.")

        self.assertRedirects(response, reverse("club:questions"))
        reply = AnswerReply.objects.get()
        self.assertEqual(reply.answer, self.answer)
        self.assertEqual(reply.author, self.bob)
        self.assertEqual(reply.body, "I disagree.")

    def test_a_valid_reply_shows_a_success_message(self):
        self.identify(self.bob)

        response = self.reply_to(self.answer.pk)
        follow = self.client.get(response.url)

        self.assertContains(follow, "Reply posted.")

    def test_a_reply_is_not_an_answer(self):
        self.identify(self.bob)

        self.reply_to(self.answer.pk)

        self.assertEqual(Answer.objects.count(), 2)

    def test_an_empty_reply_errors_under_that_answer_only(self):
        Answer.objects.create(question=self.question, member=self.bob, body="Reform.")
        self.identify(self.bob)

        response = self.reply_to(self.answer.pk, "   ")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A reply needs something in it.", count=1)
        self.assertEqual(AnswerReply.objects.count(), 0)
        answers = response.context["rows"][0]["answers"]
        self.assertEqual([a.reply_form.is_bound for a in answers], [True, False])

    def test_bad_targets_error_and_write_nothing(self):
        self.identify(self.bob)
        for target in ["", "abc", "999999", self.old_answer.pk]:
            with self.subTest(target=target):
                response = self.reply_to(target)

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Choose an answer to reply to.")
                self.assertEqual(AnswerReply.objects.count(), 0)
                self.assertEqual(Answer.objects.count(), 2)

    def test_an_empty_answer_key_never_becomes_an_answer(self):
        self.identify(self.bob)

        self.client.post(
            reverse("club:questions"),
            {"answer": "", "question": self.question.pk, "body": "Sneaky"},
        )

        self.assertEqual(Answer.objects.count(), 2)
        self.assertEqual(AnswerReply.objects.count(), 0)

    def test_an_unidentified_post_is_403_and_writes_nothing(self):
        response = self.reply_to(self.answer.pk)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(AnswerReply.objects.count(), 0)

    def test_a_deactivated_members_stale_session_is_403(self):
        self.identify(self.bob)
        self.bob.is_active = False
        self.bob.save(update_fields=["is_active"])

        response = self.reply_to(self.answer.pk)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(AnswerReply.objects.count(), 0)

    def test_with_no_current_book_a_reply_redirects_home(self):
        Book.objects.filter(pk=self.book.pk).update(is_current=False)
        self.identify(self.bob)

        response = self.reply_to(self.answer.pk)

        self.assertRedirects(response, reverse("club:home"))
        self.assertEqual(AnswerReply.objects.count(), 0)

    def test_a_member_may_reply_to_their_own_answer(self):
        self.identify(self.ada)

        self.reply_to(self.answer.pk)

        self.assertEqual(AnswerReply.objects.get().author, self.ada)

    def test_a_member_may_reply_to_a_deactivated_members_answer(self):
        self.ada.is_active = False
        self.ada.save(update_fields=["is_active"])
        self.identify(self.bob)

        self.reply_to(self.answer.pk)

        self.assertEqual(AnswerReply.objects.count(), 1)

    def test_a_member_may_reply_twice_under_one_answer(self):
        self.identify(self.bob)

        self.reply_to(self.answer.pk, "One")
        self.reply_to(self.answer.pk, "Two")

        self.assertEqual(AnswerReply.objects.count(), 2)


class AnswerReplyDisplayTests(AnswerReplyTestBase):
    def test_replies_sit_under_their_answer_oldest_first(self):
        self.make_reply(body="Second reply", offset=2)
        self.make_reply(body="First reply", offset=1)
        self.make_reply(body="Third reply", offset=3)

        content = self.client.get(reverse("club:questions")).content.decode()

        self.assertLess(content.index("First reply"), content.index("Second reply"))
        self.assertLess(content.index("Second reply"), content.index("Third reply"))
        self.assertLess(content.index("To be useful."), content.index("First reply"))

    def test_an_answer_with_no_replies_shows_no_placeholder(self):
        response = self.client.get(reverse("club:questions"))

        self.assertNotContains(response, "No replies")
        self.assertNotContains(response, "answer-reply")

    def test_a_reply_body_is_escaped(self):
        self.make_reply(body="<script>alert(1)</script>")

        response = self.client.get(reverse("club:questions"))

        self.assertNotContains(response, "<script>alert")
        self.assertContains(response, "&lt;script&gt;")

    def test_a_deactivated_authors_reply_keeps_their_name(self):
        self.make_reply(author=self.bob, body="Still here")
        self.bob.is_active = False
        self.bob.save(update_fields=["is_active"])

        response = self.client.get(reverse("club:questions"))

        self.assertContains(response, "Still here")
        self.assertContains(response, "Bob")

    def test_a_reply_does_not_change_the_answer_count_or_prefill(self):
        self.make_reply(author=self.bob)
        self.identify(self.bob)

        response = self.client.get(reverse("club:questions"))

        row = response.context["rows"][0]
        self.assertEqual(len(row["answers"]), 1)
        self.assertIsNone(row["mine"])

    def test_the_empty_state_is_unchanged(self):
        Answer.objects.filter(pk=self.answer.pk).delete()

        response = self.client.get(reverse("club:questions"))

        self.assertContains(response, "Nobody has answered this one yet.")

    def test_the_archive_shows_replies_read_only_in_order(self):
        self.make_reply(answer=self.old_answer, body="Late reply", offset=2)
        self.make_reply(answer=self.old_answer, body="Early reply", offset=1)
        self.identify(self.bob, admin=True)

        response = self.client.get(
            reverse("club:history_detail", args=[self.old_book.pk])
        )
        content = response.content.decode()

        self.assertContains(response, "Early reply", count=1)
        self.assertLess(content.index("Early reply"), content.index("Late reply"))
        self.assertNotContains(response, ">Reply</button>")
        self.assertNotContains(response, "Remove")

    def test_the_question_delete_page_mentions_replies_when_there_are_some(self):
        self.make_reply()
        self.identify(self.ada, admin=True)

        response = self.client.get(
            reverse("club:question_delete", args=[self.question.pk])
        )

        self.assertContains(response, "1 reply")

    def test_the_question_delete_page_is_unchanged_without_replies(self):
        self.identify(self.ada, admin=True)

        response = self.client.get(
            reverse("club:question_delete", args=[self.question.pk])
        )

        self.assertNotContains(response, "repl")

    def test_removing_a_question_says_how_many_replies_went_with_it(self):
        self.make_reply()
        self.make_reply(body="Another")
        self.identify(self.ada, admin=True)

        response = self.client.post(
            reverse("club:question_delete", args=[self.question.pk]), follow=True
        )

        self.assertContains(response, "2 replies")


class AnswerReplyRemovalTests(AnswerReplyTestBase):
    def setUp(self):
        self.reply = self.make_reply(author=self.bob)

    def remove(self, reply):
        return self.client.post(reverse("club:answer_reply_delete", args=[reply.pk]))

    def test_the_author_may_remove_their_reply(self):
        self.identify(self.bob)

        response = self.remove(self.reply)

        self.assertRedirects(response, reverse("club:questions"))
        self.assertFalse(AnswerReply.objects.filter(pk=self.reply.pk).exists())
        self.assertTrue(Answer.objects.filter(pk=self.answer.pk).exists())

    def test_an_admin_may_remove_it(self):
        self.identify(self.ada, admin=True)

        self.remove(self.reply)

        self.assertFalse(AnswerReply.objects.filter(pk=self.reply.pk).exists())

    def test_another_member_is_403_and_the_reply_stays(self):
        self.identify(self.ada)

        self.assertEqual(self.remove(self.reply).status_code, 403)
        self.assertTrue(AnswerReply.objects.filter(pk=self.reply.pk).exists())

    def test_an_unidentified_post_is_403(self):
        self.assertEqual(self.remove(self.reply).status_code, 403)
        self.assertTrue(AnswerReply.objects.filter(pk=self.reply.pk).exists())

    def test_a_get_is_405_and_deletes_nothing(self):
        self.identify(self.bob)

        response = self.client.get(
            reverse("club:answer_reply_delete", args=[self.reply.pk])
        )

        self.assertEqual(response.status_code, 405)
        self.assertTrue(AnswerReply.objects.filter(pk=self.reply.pk).exists())

    def test_an_unknown_pk_is_404(self):
        self.identify(self.bob)

        response = self.client.post(reverse("club:answer_reply_delete", args=[999999]))

        self.assertEqual(response.status_code, 404)

    def test_a_reply_on_a_finished_book_cannot_be_removed(self):
        old = self.make_reply(answer=self.old_answer, author=self.bob)
        self.identify(self.bob, admin=True)

        response = self.remove(old)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(AnswerReply.objects.filter(pk=old.pk).exists())

    def test_only_the_author_and_admin_see_a_remove_button(self):
        url = reverse("club:answer_reply_delete", args=[self.reply.pk])

        self.identify(self.ada)
        self.assertNotContains(self.client.get(reverse("club:questions")), url)

        self.identify(self.bob)
        self.assertContains(self.client.get(reverse("club:questions")), url)


class AnswerReplyQueryTests(AnswerReplyTestBase):
    def test_replies_do_not_add_a_query_per_answer_or_reply(self):
        self.identify(self.ada)
        with CaptureQueriesContext(connection) as small:
            self.client.get(reverse("club:questions"))

        for i in range(5):
            question = Question.objects.create(
                book=self.book, text=f"Q{i}", position=i + 2
            )
            for author in (self.ada, self.bob):
                answer = Answer.objects.create(
                    question=question, member=author, body="Yes"
                )
                for j in range(3):
                    self.make_reply(answer=answer, author=author, body=f"r{j}")

        with CaptureQueriesContext(connection) as large:
            self.client.get(reverse("club:questions"))

        self.assertEqual(len(small), len(large))

    def test_the_archive_is_pinned_and_does_not_grow_with_replies(self):
        url = reverse("club:history_detail", args=[self.old_book.pk])
        self.make_reply(answer=self.old_answer, author=self.bob)
        with CaptureQueriesContext(connection) as small:
            self.client.get(url)

        for i in range(4):
            question = Question.objects.create(
                book=self.old_book, text=f"Q{i}", position=i + 2
            )
            answer = Answer.objects.create(
                question=question, member=self.bob, body="Yes"
            )
            for j in range(3):
                self.make_reply(answer=answer, author=self.ada, body=f"r{j}")

        with self.assertNumQueries(len(small)):
            self.client.get(url)
