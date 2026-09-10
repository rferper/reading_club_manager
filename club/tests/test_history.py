"""Finishing a book, and the archive it lands in."""

from datetime import date

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from ..models import Answer, Book, Member, Note, Progress, Question


class FinishBookTests(TestCase):
    """The transition, and everything that must survive it."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.bob = Member.objects.create(name="Bob")
        cls.book = Book.objects.create(
            title="Middlemarch",
            author="George Eliot",
            total_pages=880,
            started_on=date(2025, 6, 1),
            is_current=True,
        )
        cls.progress = Progress.objects.create(
            book=cls.book, member=cls.ada, pages_read=880
        )
        cls.note = Note.objects.create(
            book=cls.book, author=cls.ada, body="Dorothea, again."
        )
        cls.question = Question.objects.create(
            book=cls.book, text="What did Dorothea want?", position=1
        )
        cls.answer = Answer.objects.create(
            question=cls.question, member=cls.bob, body="To be useful."
        )

    def setUp(self):
        session = self.client.session
        session["is_club_admin"] = True
        session.save()
        self.url = reverse("club:book_finish", args=[self.book.pk])

    def test_finishing_records_the_date_and_clears_the_flag(self):
        response = self.client.post(
            self.url, {"finished_on": "2025-09-01", "rating": "4"}
        )

        self.assertRedirects(
            response, reverse("club:history_detail", args=[self.book.pk])
        )
        self.book.refresh_from_db()
        self.assertEqual(self.book.finished_on, date(2025, 9, 1))
        self.assertEqual(self.book.rating, 4)
        self.assertIs(self.book.is_current, False)
        self.assertIsNone(Book.objects.current())

    def test_the_discussion_survives_the_transition_unchanged(self):
        """The test that matters. Decision #2 chose one table with a flag
        precisely so that finishing a book cannot lose any of this."""
        self.client.post(self.url, {"finished_on": "2025-09-01", "rating": "4"})

        self.progress.refresh_from_db()
        self.assertEqual(self.progress.book, self.book)
        self.assertEqual(self.progress.pages_read, 880)

        self.note.refresh_from_db()
        self.assertEqual(self.note.book, self.book)
        self.assertEqual(self.note.body, "Dorothea, again.")

        self.question.refresh_from_db()
        self.assertEqual(self.question.book, self.book)

        self.answer.refresh_from_db()
        self.assertEqual(self.answer.question, self.question)
        self.assertEqual(self.answer.body, "To be useful.")
        self.assertEqual(self.answer.member, self.bob)

    def test_nothing_at_all_is_deleted(self):
        counts = (
            Progress.objects.count(),
            Note.objects.count(),
            Question.objects.count(),
            Answer.objects.count(),
            Book.objects.count(),
        )

        self.client.post(self.url, {"finished_on": "2025-09-01", "rating": "4"})

        self.assertEqual(
            counts,
            (
                Progress.objects.count(),
                Note.objects.count(),
                Question.objects.count(),
                Answer.objects.count(),
                Book.objects.count(),
            ),
        )

    def test_the_landing_page_falls_back_to_its_empty_state(self):
        self.client.post(self.url, {"finished_on": "2025-09-01", "rating": "4"})

        response = self.client.get(reverse("club:home"))

        self.assertContains(response, "No book in progress")
        self.assertNotContains(response, "We are reading")

    def test_the_book_appears_in_the_archive(self):
        self.client.post(self.url, {"finished_on": "2025-09-01", "rating": "4"})

        response = self.client.get(reverse("club:history"))

        self.assertContains(response, "Middlemarch")
        self.assertContains(response, "the club said 4 out of 5")

    def test_the_finish_form_offers_today_as_the_date(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["form"].initial["finished_on"], timezone.localdate()
        )

    def test_the_confirmation_says_the_discussion_is_kept(self):
        response = self.client.get(self.url)

        self.assertContains(response, "Middlemarch")
        self.assertContains(response, "the archive keeps the whole discussion")

    def test_a_rating_is_optional(self):
        self.client.post(self.url, {"finished_on": "2025-09-01", "rating": ""})

        self.book.refresh_from_db()
        self.assertIsNone(self.book.rating)
        self.assertIs(self.book.is_current, False)

    def test_a_rating_outside_one_to_five_is_a_form_error(self):
        response = self.client.post(
            self.url, {"finished_on": "2025-09-01", "rating": "9"}
        )

        self.assertEqual(response.status_code, 200)
        self.book.refresh_from_db()
        self.assertIs(self.book.is_current, True)

    def test_a_missing_finish_date_is_a_form_error(self):
        """Nullable on the model, because a book being read has no finish date.
        Required here, because this form is the moment it gets one."""
        response = self.client.post(self.url, {"finished_on": "", "rating": "4"})

        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "finished_on",
            "A finished book needs the date it was finished.",
        )
        self.book.refresh_from_db()
        self.assertIs(self.book.is_current, True)

    def test_finishing_a_book_that_is_not_current_is_a_404(self):
        other = Book.objects.create(title="Piranesi", author="Susanna Clarke")

        response = self.client.post(
            reverse("club:book_finish", args=[other.pk]),
            {"finished_on": "2025-09-01"},
        )

        self.assertEqual(response.status_code, 404)

    def test_a_non_admin_cannot_finish_a_book(self):
        self.client.post(reverse("club:admin_exit"))

        response = self.client.post(self.url, {"finished_on": "2025-09-01"})

        self.assertEqual(response.status_code, 403)
        self.book.refresh_from_db()
        self.assertIs(self.book.is_current, True)

    def test_a_get_finishes_nothing(self):
        self.client.get(self.url)

        self.book.refresh_from_db()
        self.assertIs(self.book.is_current, True)


class FinishedBookIsReadOnlyTests(TestCase):
    """The URLs still exist. The book is closed anyway."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.book = Book.objects.create(
            title="Middlemarch",
            author="George Eliot",
            finished_on=date(2025, 9, 1),
        )
        cls.question = Question.objects.create(
            book=cls.book, text="What did Dorothea want?", position=1
        )

    def setUp(self):
        session = self.client.session
        session["member_id"] = self.ada.pk
        session.save()

    def test_a_note_cannot_be_posted_against_a_finished_book(self):
        response = self.client.post(
            reverse("club:notes"), {"body": "One more thought"}, follow=True
        )

        self.assertRedirects(response, reverse("club:home"))
        self.assertEqual(Note.objects.count(), 0)

    def test_an_answer_cannot_be_posted_against_a_finished_books_question(self):
        response = self.client.post(
            reverse("club:questions"),
            {"question": self.question.pk, "body": "Too late"},
            follow=True,
        )

        self.assertEqual(Answer.objects.count(), 0)
        self.assertNotEqual(response.status_code, 500)

    def test_progress_cannot_be_recorded_against_a_finished_book(self):
        response = self.client.post(
            reverse("club:progress_update"), {"pages_read": "100"}, follow=True
        )

        self.assertRedirects(response, reverse("club:home"))
        self.assertEqual(Progress.objects.count(), 0)

    def test_the_archive_page_closes_the_discussion(self):
        """Narrowed by #16: ratings stay open, because you rate a book once you
        have finished it. Nothing that adds to the discussion does."""
        response = self.client.get(
            reverse("club:history_detail", args=[self.book.pk])
        )

        self.assertContains(response, "The discussion is closed")
        self.assertNotContains(response, "Post note")
        self.assertNotContains(response, "Post answer")
        self.assertNotContains(response, "Edit your answer")
        # Nothing to type into. The rating form is a set of five scores, and
        # every way of adding to the discussion is a body of text.
        self.assertNotContains(response, "<textarea")


class StartBookTests(TestCase):
    """Making a book the club's current read."""

    def setUp(self):
        session = self.client.session
        session["is_club_admin"] = True
        session.save()

    def test_an_admin_can_start_a_book(self):
        response = self.client.post(
            reverse("club:book_start"),
            {
                "title": "Piranesi",
                "author": "Susanna Clarke",
                "total_pages": "245",
                "started_on": "2025-09-08",
            },
            follow=True,
        )

        self.assertRedirects(response, reverse("club:home"))
        book = Book.objects.get()
        self.assertIs(book.is_current, True)
        self.assertEqual(book.started_on, date(2025, 9, 8))
        self.assertContains(response, "Piranesi")

    def test_the_form_offers_today_as_the_start_date(self):
        response = self.client.get(reverse("club:book_start"))

        self.assertEqual(
            response.context["form"].initial["started_on"], timezone.localdate()
        )

    def test_starting_a_second_book_is_a_readable_refusal(self):
        """Not an IntegrityError page. The constraint is real; this is the
        sentence a club member reads instead of a traceback."""
        Book.objects.create(
            title="Middlemarch", author="George Eliot", is_current=True
        )

        response = self.client.post(
            reverse("club:book_start"),
            {"title": "Piranesi", "author": "Susanna Clarke", "started_on": ""},
            follow=True,
        )

        self.assertRedirects(response, reverse("club:home"))
        self.assertContains(response, "already reading Middlemarch")
        self.assertEqual(Book.objects.count(), 1)

    def test_the_form_carries_no_current_flag(self):
        response = self.client.get(reverse("club:book_start"))

        self.assertNotIn("is_current", response.context["form"].fields)

    def test_a_submitted_current_flag_is_ignored_on_a_second_book(self):
        Book.objects.create(
            title="Middlemarch", author="George Eliot", is_current=True
        )

        self.client.post(
            reverse("club:book_start"),
            {
                "title": "Piranesi",
                "author": "Susanna Clarke",
                "started_on": "",
                "is_current": "on",
            },
        )

        self.assertEqual(Book.objects.filter(is_current=True).count(), 1)

    def test_a_non_admin_cannot_start_a_book(self):
        self.client.post(reverse("club:admin_exit"))

        response = self.client.post(
            reverse("club:book_start"),
            {"title": "Piranesi", "author": "Susanna Clarke", "started_on": ""},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Book.objects.count(), 0)

    def test_a_book_needs_a_title_and_an_author(self):
        response = self.client.post(
            reverse("club:book_start"), {"title": "", "author": "", "started_on": ""}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Book.objects.count(), 0)


class HistoryListTests(TestCase):
    """The archive, uncapped and newest first."""

    @classmethod
    def setUpTestData(cls):
        cls.older = Book.objects.create(
            title="Piranesi",
            author="Susanna Clarke",
            started_on=date(2024, 1, 1),
            finished_on=date(2024, 3, 1),
            rating=5,
        )
        cls.newer = Book.objects.create(
            title="Middlemarch",
            author="George Eliot",
            started_on=date(2025, 1, 1),
            finished_on=date(2025, 6, 1),
        )
        cls.reading = Book.objects.create(
            title="Ulysses", author="James Joyce", is_current=True
        )

    def test_finished_books_are_listed_newest_first(self):
        response = self.client.get(reverse("club:history"))

        self.assertEqual(
            list(response.context["books"]), [self.newer, self.older]
        )

    def test_the_current_read_is_not_in_the_archive(self):
        response = self.client.get(reverse("club:history"))

        self.assertNotContains(response, "Ulysses")

    def test_each_entry_shows_its_dates_and_rating(self):
        response = self.client.get(reverse("club:history"))

        self.assertContains(response, "Susanna Clarke")
        self.assertContains(response, "the club said 5 out of 5")

    def test_a_book_with_no_rating_says_nothing_about_one(self):
        response = self.client.get(reverse("club:history"))

        self.assertNotContains(response, "the club said 0")
        self.assertNotContains(response, "members averaged 0")

    def test_a_book_with_no_finish_date_says_so_rather_than_going_blank(self):
        Book.objects.create(title="Abandoned", author="Nobody")

        response = self.client.get(reverse("club:history"))

        self.assertContains(response, "no finish date recorded")

    def test_the_archive_is_uncapped(self):
        for index in range(30):
            Book.objects.create(
                title=f"Book {index:02d}",
                author="A",
                finished_on=date(2020, 1, 1),
            )

        response = self.client.get(reverse("club:history"))

        self.assertEqual(len(response.context["books"]), 32)

    def test_the_nav_reaches_the_history(self):
        response = self.client.get(reverse("club:home"))

        self.assertContains(response, reverse("club:history"))

    def test_a_non_admin_sees_no_edit_controls(self):
        response = self.client.get(reverse("club:history"))

        self.assertNotContains(response, reverse("club:book_start"))
        self.assertNotContains(response, reverse("club:book_edit", args=[self.older.pk]))

    def test_an_admin_sees_them(self):
        session = self.client.session
        session["is_club_admin"] = True
        session.save()

        response = self.client.get(reverse("club:history"))

        self.assertContains(response, reverse("club:book_edit", args=[self.older.pk]))


class EmptyHistoryTests(TestCase):
    """Before the club has finished anything."""

    def test_the_page_names_what_is_missing(self):
        response = self.client.get(reverse("club:history"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "has not finished a book yet")

    def test_a_current_book_alone_does_not_fill_the_archive(self):
        Book.objects.create(
            title="Middlemarch", author="George Eliot", is_current=True
        )

        response = self.client.get(reverse("club:history"))

        self.assertContains(response, "has not finished a book yet")


class HistoryDetailTests(TestCase):
    """One past book, replayed."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.bob = Member.objects.create(name="Bob")
        cls.book = Book.objects.create(
            title="Middlemarch",
            author="George Eliot",
            total_pages=880,
            started_on=date(2025, 1, 1),
            finished_on=date(2025, 6, 1),
            rating=4,
        )
        Progress.objects.create(book=cls.book, member=cls.ada, pages_read=440)
        Note.objects.create(book=cls.book, author=cls.ada, body="Dorothea, again.")
        cls.question = Question.objects.create(
            book=cls.book, text="What did Dorothea want?", position=1
        )
        Answer.objects.create(
            question=cls.question, member=cls.bob, body="To be useful."
        )

    def test_the_page_replays_the_whole_discussion(self):
        response = self.client.get(
            reverse("club:history_detail", args=[self.book.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Middlemarch")
        self.assertContains(response, "Dorothea, again.")
        self.assertContains(response, "What did Dorothea want?")
        self.assertContains(response, "To be useful.")

    def test_progress_is_shown_with_its_percentage(self):
        response = self.client.get(
            reverse("club:history_detail", args=[self.book.pk])
        )

        self.assertContains(response, "440 pages")
        self.assertContains(response, "50%")

    def test_a_book_with_no_page_count_shows_pages_and_no_percentage(self):
        self.book.total_pages = None
        self.book.save(update_fields=["total_pages"])

        response = self.client.get(
            reverse("club:history_detail", args=[self.book.pk])
        )

        self.assertContains(response, "440 pages")
        self.assertNotContains(response, "%")

    def test_names_survive_their_members_deactivation(self):
        self.ada.is_active = False
        self.ada.save(update_fields=["is_active"])

        response = self.client.get(
            reverse("club:history_detail", args=[self.book.pk])
        )

        self.assertContains(response, "Ada")
        self.assertContains(response, "Dorothea, again.")

    def test_a_book_nobody_wrote_anything_about_says_so_three_times(self):
        bare = Book.objects.create(
            title="Bare", author="A", finished_on=date(2025, 1, 1)
        )

        response = self.client.get(reverse("club:history_detail", args=[bare.pk]))

        self.assertContains(response, "Nobody recorded any progress")
        self.assertContains(response, "No notes were written")
        self.assertContains(response, "No questions were posted")

    def test_a_book_that_is_not_there_is_a_404(self):
        response = self.client.get(reverse("club:history_detail", args=[9999]))

        self.assertEqual(response.status_code, 404)

    def test_the_current_read_is_shown_as_still_open(self):
        """Reaching this page for the current book is not an error — it is the
        same replay, of a discussion that has not finished happening."""
        reading = Book.objects.create(
            title="Ulysses", author="James Joyce", is_current=True
        )

        response = self.client.get(reverse("club:history_detail", args=[reading.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "still open")
        self.assertNotContains(response, "Read-only")


class BookEditTests(TestCase):
    """Correcting an entry, without touching what hangs off it."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.book = Book.objects.create(
            title="Middlemarch",
            author="George Elliot",
            finished_on=date(2025, 6, 1),
        )
        cls.note = Note.objects.create(
            book=cls.book, author=cls.ada, body="Dorothea, again."
        )

    def setUp(self):
        session = self.client.session
        session["is_club_admin"] = True
        session.save()
        self.url = reverse("club:book_edit", args=[self.book.pk])

    def test_an_admin_can_fix_a_misspelled_author(self):
        response = self.client.post(
            self.url,
            {
                "title": "Middlemarch",
                "author": "George Eliot",
                "total_pages": "880",
                "started_on": "2025-01-01",
                "finished_on": "2025-06-01",
                "rating": "4",
            },
        )

        self.assertRedirects(
            response, reverse("club:history_detail", args=[self.book.pk])
        )
        self.book.refresh_from_db()
        self.assertEqual(self.book.author, "George Eliot")
        self.assertEqual(self.book.rating, 4)

    def test_editing_leaves_the_discussion_alone(self):
        self.client.post(
            self.url,
            {
                "title": "Middlemarch",
                "author": "George Eliot",
                "total_pages": "",
                "started_on": "",
                "finished_on": "2025-06-01",
                "rating": "",
            },
        )

        self.note.refresh_from_db()
        self.assertEqual(self.note.body, "Dorothea, again.")
        self.assertEqual(self.note.book, self.book)

    def test_the_form_cannot_move_the_current_read_flag(self):
        response = self.client.get(self.url)

        self.assertNotIn("is_current", response.context["form"].fields)

    def test_a_submitted_current_flag_is_ignored(self):
        self.client.post(
            self.url,
            {
                "title": "Middlemarch",
                "author": "George Eliot",
                "total_pages": "",
                "started_on": "",
                "finished_on": "2025-06-01",
                "rating": "",
                "is_current": "on",
            },
        )

        self.book.refresh_from_db()
        self.assertIs(self.book.is_current, False)

    def test_editing_the_current_book_returns_to_the_landing_page(self):
        reading = Book.objects.create(
            title="Ulysses", author="James Joyce", is_current=True
        )

        response = self.client.post(
            reverse("club:book_edit", args=[reading.pk]),
            {
                "title": "Ulysses",
                "author": "James Joyce",
                "total_pages": "730",
                "started_on": "",
                "finished_on": "",
                "rating": "",
            },
        )

        self.assertRedirects(response, reverse("club:home"))

    def test_a_non_admin_cannot_edit_an_entry(self):
        self.client.post(reverse("club:admin_exit"))

        response = self.client.post(
            self.url,
            {
                "title": "Vandalised",
                "author": "Nobody",
                "total_pages": "",
                "started_on": "",
                "finished_on": "",
                "rating": "",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.book.refresh_from_db()
        self.assertEqual(self.book.title, "Middlemarch")


class FullCycleTests(TestCase):
    """Start a book, read it, finish it, start the next one."""

    def setUp(self):
        self.ada = Member.objects.create(name="Ada")
        session = self.client.session
        session["is_club_admin"] = True
        session["member_id"] = self.ada.pk
        session.save()

    def test_the_club_can_go_round_twice_without_getting_stuck(self):
        self.client.post(
            reverse("club:book_start"),
            {
                "title": "Middlemarch",
                "author": "George Eliot",
                "total_pages": "880",
                "started_on": "2025-01-01",
            },
        )
        first = Book.objects.get(title="Middlemarch")
        self.client.post(reverse("club:progress_update"), {"pages_read": "880"})
        self.client.post(reverse("club:notes"), {"body": "Finished it."})

        self.client.post(
            reverse("club:book_finish", args=[first.pk]),
            {"finished_on": "2025-06-01", "rating": "5"},
        )

        self.assertIsNone(Book.objects.current())

        self.client.post(
            reverse("club:book_start"),
            {
                "title": "Piranesi",
                "author": "Susanna Clarke",
                "total_pages": "245",
                "started_on": "2025-06-02",
            },
        )
        second = Book.objects.get(title="Piranesi")

        self.assertEqual(Book.objects.current(), second)
        self.assertEqual(Progress.objects.get().book, first)
        self.assertEqual(Note.objects.get().book, first)

        history = self.client.get(reverse("club:history"))
        self.assertEqual(list(history.context["books"]), [first])


class HistoryMixesMeasuresTests(TestCase):
    """The archive holds a page-measured book and a chapter-measured one (#17).

    The percentage is the one figure comparable across the two, which is
    decision #1 doing its job — and it is still stored nowhere.
    """

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.bob = Member.objects.create(name="Bob")
        cls.in_pages = Book.objects.create(
            title="Middlemarch",
            author="George Eliot",
            total_pages=880,
            started_on=date(2025, 1, 1),
            finished_on=date(2025, 6, 1),
        )
        cls.in_chapters = Book.objects.create(
            title="Piranesi",
            author="Susanna Clarke",
            total_chapters=30,
            started_on=date(2025, 6, 2),
            finished_on=date(2025, 8, 1),
        )
        Progress.objects.create(book=cls.in_pages, member=cls.ada, pages_read=440)
        Progress.objects.create(book=cls.in_chapters, member=cls.ada, chapters_read=12)
        Progress.objects.create(book=cls.in_chapters, member=cls.bob, chapters_read=30)

    def test_the_archive_lists_both_books_each_naming_its_own_unit(self):
        response = self.client.get(reverse("club:history"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "880 pages")
        self.assertContains(response, "30 chapters")

    def test_the_chapter_books_entry_counts_in_chapters(self):
        response = self.client.get(
            reverse("club:history_detail", args=[self.in_chapters.pk])
        )

        self.assertContains(response, "12 chapters, 40%")
        self.assertNotContains(response, "12 pages")

    def test_the_page_books_entry_still_counts_in_pages(self):
        response = self.client.get(
            reverse("club:history_detail", args=[self.in_pages.pk])
        )

        self.assertContains(response, "440 pages")
        self.assertContains(response, "50%")

    def test_a_chapter_books_progress_lists_furthest_first(self):
        """It used to list by `pages_read`, a column nobody wrote to here."""
        response = self.client.get(
            reverse("club:history_detail", args=[self.in_chapters.pk])
        )

        listed = [row.member.name for row in response.context["progress"]]
        self.assertEqual(listed, ["Bob", "Ada"])

    def test_a_row_left_behind_by_a_measure_change_reads_as_not_started(self):
        """Decision #19: 431 pages on a book now counted in chapters is
        nothing recorded, not a zero — and the pages are still there."""
        Progress.objects.filter(book=self.in_chapters, member=self.ada).update(
            pages_read=431, chapters_read=None
        )

        response = self.client.get(
            reverse("club:history_detail", args=[self.in_chapters.pk])
        )

        self.assertContains(response, "not started")
        self.assertNotContains(response, "431")

    def test_the_percentage_is_the_figure_the_two_books_share(self):
        """Nothing stores it — both come off `Book.percent_of`."""
        pages_row = Progress.objects.select_related("book").get(book=self.in_pages)
        chapters_row = Progress.objects.select_related("book").get(
            book=self.in_chapters, member=self.bob
        )

        self.assertEqual(pages_row.percent, 50)
        self.assertEqual(chapters_row.percent, 100)

    def test_starting_a_book_in_chapters_goes_through_the_same_form(self):
        session = self.client.session
        session["is_club_admin"] = True
        session.save()

        self.client.post(
            reverse("club:book_start"),
            {
                "title": "Ancillary Justice",
                "author": "Ann Leckie",
                "total_pages": "",
                "total_chapters": "26",
                "started_on": "2025-09-01",
            },
        )

        started = Book.objects.get(title="Ancillary Justice")
        self.assertEqual(started.measure, "chapters")
        self.assertIs(started.is_current, True)

    def test_starting_a_book_with_both_counts_is_refused_on_the_page(self):
        session = self.client.session
        session["is_club_admin"] = True
        session.save()

        response = self.client.post(
            reverse("club:book_start"),
            {
                "title": "Both",
                "author": "A",
                "total_pages": "300",
                "total_chapters": "26",
                "started_on": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Book.objects.filter(title="Both").exists())
        self.assertContains(response, "pages or in chapters")
