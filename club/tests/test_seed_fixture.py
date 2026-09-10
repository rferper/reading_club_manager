"""The development fixture, checked by loading it and walking the whole app.

The fixture doubles as manual test data. Its job is to put the awkward states
in front of a newcomer's eyes — a deactivated member whose writing keeps her
name, a member with nothing recorded, and a finished book that kept its
discussion — so these tests assert those are actually in there, not just that
the JSON parses.
"""

from django.test import TestCase
from django.urls import reverse

from ..models import Answer, Book, Member, MemberRating, Note, Progress, Question


class SeedFixtureTests(TestCase):
    """What `loaddata dev_seed` puts in the database."""

    fixtures = ["dev_seed"]

    def test_it_loads(self):
        self.assertGreater(Member.objects.count(), 0)
        self.assertGreater(Book.objects.count(), 0)

    def test_there_is_one_current_book_and_at_least_one_finished_one(self):
        current = Book.objects.current()

        self.assertIsNotNone(current)
        self.assertTrue(
            Book.objects.filter(is_current=False, finished_on__isnull=False).exists()
        )

    def test_one_member_is_deactivated(self):
        """So the roster shows the marked state, and the archive shows a name
        outliving the member it belongs to."""
        self.assertTrue(Member.objects.filter(is_active=False).exists())
        self.assertGreater(Member.objects.filter(is_active=True).count(), 2)

    def test_a_deactivated_member_still_has_writing_in_the_archive(self):
        departed = Member.objects.filter(is_active=False).first()

        self.assertTrue(
            departed.notes.exists() or departed.answers.exists(),
            "a fixture whose departed member wrote nothing proves nothing",
        )

    def test_some_but_not_all_active_members_have_progress_on_the_current_book(self):
        """The overview's whole point is who is behind, which needs somebody
        who is — and somebody who has recorded nothing at all."""
        current = Book.objects.current()
        active = Member.objects.filter(is_active=True)
        with_progress = set(
            Progress.objects.filter(book=current).values_list("member_id", flat=True)
        )

        self.assertTrue(with_progress)
        self.assertTrue(
            {member.pk for member in active} - with_progress,
            "every active member has progress; nobody is behind",
        )

    def test_the_current_book_has_questions_answered_by_more_than_one_member(self):
        current = Book.objects.current()
        questions = Question.objects.filter(book=current)

        self.assertGreaterEqual(questions.count(), 2)
        answerers = set(
            Answer.objects.filter(question__in=questions).values_list(
                "member_id", flat=True
            )
        )
        self.assertGreaterEqual(len(answerers), 2)

    def test_the_finished_book_kept_its_own_notes_and_answers(self):
        finished = Book.objects.filter(is_current=False).first()

        self.assertTrue(Note.objects.filter(book=finished).exists())
        self.assertTrue(Answer.objects.filter(question__book=finished).exists())

    def test_a_note_spans_more_than_one_paragraph(self):
        """So a newcomer sees that line breaks survive, without typing one."""
        self.assertTrue(
            any("\n\n" in note.body for note in Note.objects.all()),
            "no seeded note has a blank line in it",
        )

    def test_the_finished_book_carries_a_rating(self):
        finished = Book.objects.filter(is_current=False).first()

        self.assertIsNotNone(finished.rating)

    def test_the_finished_book_also_carries_member_ratings(self):
        """#16: the club's own number and the members' scores are different
        facts (decision #9), and the fixture has to show both or the archive
        looks like it only has one."""
        finished = Book.objects.filter(is_current=False).first()

        self.assertGreaterEqual(finished.ratings.count(), 3)

    def test_the_seeded_scores_disagree_with_each_other(self):
        """An average that equals every score in it teaches nothing."""
        scores = set(MemberRating.objects.values_list("score", flat=True))

        self.assertGreater(len(scores), 1, "every seeded member scored the same")

    def test_the_member_average_is_not_the_clubs_own_number(self):
        finished = Book.objects.filter(is_current=False).first()
        scores = list(finished.ratings.values_list("score", flat=True))

        self.assertNotEqual(sum(scores) / len(scores), finished.rating)

    def test_the_deactivated_member_left_a_rating_behind(self):
        """Decision #3: her score stays in the average and keeps her name."""
        departed = Member.objects.filter(is_active=False).first()

        self.assertTrue(departed.ratings.exists())

    def test_somebody_has_not_rated_the_finished_book(self):
        """So the seed shows a partial spread rather than a full house."""
        finished = Book.objects.filter(is_current=False).first()
        rated = set(finished.ratings.values_list("member_id", flat=True))

        self.assertTrue(
            {member.pk for member in Member.objects.all()} - rated,
            "every seeded member rated it; nobody is missing",
        )


class SeededPagesRenderRealContentTests(TestCase):
    """Every page, with the fixture loaded, showing content and not an empty state."""

    fixtures = ["dev_seed"]

    def test_every_public_page_renders_with_real_content(self):
        finished = Book.objects.filter(is_current=False).first()
        pages = (
            reverse("club:home"),
            reverse("club:member_list"),
            reverse("club:progress"),
            reverse("club:notes"),
            reverse("club:questions"),
            reverse("club:history"),
            reverse("club:history_detail", args=[finished.pk]),
            reverse("club:identify"),
        )

        for url in pages:
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertEqual(response.status_code, 200)

    def test_no_page_falls_back_to_the_between_reads_empty_state(self):
        for url in (
            reverse("club:home"),
            reverse("club:progress"),
            reverse("club:notes"),
            reverse("club:questions"),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertNotContains(response, "No book in progress")

    def test_the_archive_shows_a_member_average_without_typing_one(self):
        response = self.client.get(reverse("club:history"))

        self.assertContains(response, "members averaged")

    def test_the_archive_entry_shows_every_seeded_score_with_its_name(self):
        finished = Book.objects.filter(is_current=False).first()

        response = self.client.get(
            reverse("club:history_detail", args=[finished.pk])
        )

        for rating in finished.ratings.select_related("member"):
            with self.subTest(member=rating.member.name):
                self.assertContains(
                    response, f"{rating.member.name} — {rating.score} out of 5"
                )

    def test_the_archive_is_not_empty(self):
        response = self.client.get(reverse("club:history"))

        self.assertNotContains(response, "has not finished a book yet")

    def test_the_progress_overview_shows_somebody_who_has_not_started(self):
        response = self.client.get(reverse("club:progress"))

        self.assertContains(response, "not started")

    def test_the_archive_shows_a_departed_members_name(self):
        departed = Member.objects.filter(is_active=False).first()
        finished = Note.objects.filter(author=departed).first().book

        response = self.client.get(
            reverse("club:history_detail", args=[finished.pk])
        )

        self.assertContains(response, departed.name)

    def test_a_seeded_member_can_record_progress_without_anything_else(self):
        """The path a newcomer takes first: pick a name, type a number."""
        dev = Member.objects.filter(
            is_active=True, progress__isnull=True
        ).distinct().first()
        self.assertIsNotNone(dev)

        self.client.post(reverse("club:identify"), {"member": dev.pk})
        response = self.client.post(
            reverse("club:progress_update"), {"pages_read": "12"}, follow=True
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Progress.objects.get(member=dev).pages_read, 12)
