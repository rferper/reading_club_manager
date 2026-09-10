"""Per-member ratings on finished books, beside the club's own number."""

from datetime import date

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase
from django.urls import reverse

from ..models import Book, Member, MemberRating


class MemberRatingModelTests(TestCase):
    """One score per member per book, and the database says so."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.book = Book.objects.create(
            title="Piranesi", author="Susanna Clarke", finished_on=date(2025, 6, 1)
        )

    def test_a_second_score_from_the_same_member_is_rejected(self):
        MemberRating.objects.create(book=self.book, member=self.ada, score=4)

        with self.assertRaises(IntegrityError), transaction.atomic():
            MemberRating.objects.create(book=self.book, member=self.ada, score=5)

    def test_a_duplicate_is_a_validation_error_before_that(self):
        MemberRating.objects.create(book=self.book, member=self.ada, score=4)

        with self.assertRaises(ValidationError):
            MemberRating(book=self.book, member=self.ada, score=5).full_clean()

    def test_two_members_may_rate_the_same_book(self):
        bob = Member.objects.create(name="Bob")
        MemberRating.objects.create(book=self.book, member=self.ada, score=4)
        MemberRating.objects.create(book=self.book, member=bob, score=2)

        self.assertEqual(self.book.ratings.count(), 2)

    def test_one_member_may_rate_two_books(self):
        other = Book.objects.create(
            title="Middlemarch", author="George Eliot", finished_on=date(2024, 1, 1)
        )
        MemberRating.objects.create(book=self.book, member=self.ada, score=4)
        MemberRating.objects.create(book=other, member=self.ada, score=5)

        self.assertEqual(self.ada.ratings.count(), 2)

    def test_a_score_outside_one_to_five_is_refused_by_the_database(self):
        for score in (0, 6):
            with self.subTest(score=score):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    MemberRating.objects.create(
                        book=self.book, member=self.ada, score=score
                    )

    def test_a_score_outside_one_to_five_is_a_validation_error(self):
        with self.assertRaises(ValidationError) as caught:
            MemberRating(book=self.book, member=self.ada, score=9).full_clean()

        self.assertIn("score", caught.exception.message_dict)

    def test_a_member_with_ratings_cannot_be_deleted(self):
        """Decision #3 and #20: their score stays in the average."""
        MemberRating.objects.create(book=self.book, member=self.ada, score=4)

        with self.assertRaises(ProtectedError):
            self.ada.delete()

    def test_deleting_a_book_takes_its_ratings(self):
        MemberRating.objects.create(book=self.book, member=self.ada, score=4)

        self.book.delete()

        self.assertEqual(MemberRating.objects.count(), 0)

    def test_the_club_rating_and_the_member_ratings_are_different_facts(self):
        """Decision #9 keeps `Book.rating` as the number the club agreed out
        loud. Neither is derived from the other, and both can be present."""
        self.book.rating = 5
        self.book.save(update_fields=["rating"])
        MemberRating.objects.create(book=self.book, member=self.ada, score=2)

        self.book.refresh_from_db()
        self.assertEqual(self.book.rating, 5)
        self.assertEqual(self.book.ratings.get().score, 2)


class RateBookTests(TestCase):
    """Submitting your own score."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.book = Book.objects.create(
            title="Piranesi",
            author="Susanna Clarke",
            finished_on=date(2025, 6, 1),
            rating=5,
        )

    def setUp(self):
        session = self.client.session
        session["member_id"] = self.ada.pk
        session.save()
        self.url = reverse("club:book_rate", args=[self.book.pk])

    def test_a_member_can_rate_a_finished_book(self):
        response = self.client.post(self.url, {"score": "4"}, follow=True)

        self.assertRedirects(
            response, reverse("club:history_detail", args=[self.book.pk])
        )
        self.assertEqual(MemberRating.objects.get().score, 4)
        self.assertContains(response, "Your rating for Piranesi is saved.")

    def test_rating_twice_replaces_rather_than_adds(self):
        self.client.post(self.url, {"score": "2"})
        self.client.post(self.url, {"score": "5"})

        self.assertEqual(MemberRating.objects.count(), 1)
        self.assertEqual(MemberRating.objects.get().score, 5)

    def test_the_form_offers_only_one_to_five(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [choice for choice, _ in response.context["form"].fields["score"].choices],
            [1, 2, 3, 4, 5],
        )

    def test_a_score_outside_the_range_is_a_form_error(self):
        response = self.client.post(self.url, {"score": "9"})

        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"], "score", "A rating runs from 1 to 5."
        )
        self.assertEqual(MemberRating.objects.count(), 0)

    def test_the_standalone_form_starts_blank_for_a_first_rating(self):
        response = self.client.get(self.url)

        self.assertIsNone(response.context["form"].initial.get("score"))

    def test_the_standalone_form_is_prefilled_with_an_existing_score(self):
        MemberRating.objects.create(book=self.book, member=self.ada, score=3)

        response = self.client.get(self.url)

        self.assertEqual(response.context["form"].initial["score"], 3)
        self.assertContains(response, 'value="3" selected')

    def test_the_standalone_form_shows_somebody_elses_score_to_nobody(self):
        bob = Member.objects.create(name="Bob")
        MemberRating.objects.create(book=self.book, member=bob, score=1)

        response = self.client.get(self.url)

        self.assertIsNone(response.context["form"].initial.get("score"))

    def test_the_form_carries_neither_member_nor_book(self):
        response = self.client.get(self.url)

        self.assertEqual(list(response.context["form"].fields), ["score"])

    def test_a_submitted_member_is_ignored(self):
        bob = Member.objects.create(name="Bob")

        self.client.post(self.url, {"score": "4", "member": bob.pk})

        self.assertEqual(MemberRating.objects.get().member, self.ada)

    def test_two_members_rate_separately(self):
        bob = Member.objects.create(name="Bob")
        self.client.post(self.url, {"score": "2"})

        session = self.client.session
        session["member_id"] = bob.pk
        session.save()
        self.client.post(self.url, {"score": "5"})

        self.assertEqual(MemberRating.objects.count(), 2)
        self.assertEqual(MemberRating.objects.get(member=bob).score, 5)

    def test_a_book_that_is_not_there_is_a_404(self):
        response = self.client.post(
            reverse("club:book_rate", args=[9999]), {"score": "4"}
        )

        self.assertEqual(response.status_code, 404)


class RatingTheCurrentReadTests(TestCase):
    """You rate what you have finished."""

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
        self.url = reverse("club:book_rate", args=[self.book.pk])

    def test_a_post_is_refused_and_stores_nothing(self):
        response = self.client.post(self.url, {"score": "4"}, follow=True)

        self.assertRedirects(
            response, reverse("club:history_detail", args=[self.book.pk])
        )
        self.assertContains(response, "still reading Middlemarch")
        self.assertEqual(MemberRating.objects.count(), 0)

    def test_the_form_is_not_offered(self):
        response = self.client.get(self.url, follow=True)

        self.assertContains(response, "still reading Middlemarch")

    def test_the_detail_page_offers_no_rating_link(self):
        response = self.client.get(
            reverse("club:history_detail", args=[self.book.pk])
        )

        self.assertNotContains(response, reverse("club:book_rate", args=[self.book.pk]))
        self.assertContains(response, "the club is still reading it")


class RatingIdentityTests(TestCase):
    """Nobody rates as nobody."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.book = Book.objects.create(
            title="Piranesi", author="Susanna Clarke", finished_on=date(2025, 6, 1)
        )

    def test_an_unidentified_post_is_refused_rather_than_redirected(self):
        """Decision #16."""
        response = self.client.post(
            reverse("club:book_rate", args=[self.book.pk]), {"score": "4"}
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(MemberRating.objects.count(), 0)

    def test_an_unidentified_get_is_sent_to_the_picker_and_comes_back(self):
        url = reverse("club:book_rate", args=[self.book.pk])

        response = self.client.get(url)

        self.assertRedirects(
            response,
            reverse("club:identify") + "?next=" + url,
            fetch_redirect_response=False,
        )

    def test_the_detail_page_invites_a_stranger_to_identify(self):
        response = self.client.get(
            reverse("club:history_detail", args=[self.book.pk])
        )

        self.assertContains(response, "to add your own rating")
        self.assertNotContains(
            response, reverse("club:book_rate", args=[self.book.pk])
        )


class RatingsOnTheArchiveTests(TestCase):
    """What the spread looks like once it exists."""

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.bob = Member.objects.create(name="Bob")
        cls.zoe = Member.objects.create(name="Zoe", is_active=False)
        cls.book = Book.objects.create(
            title="Piranesi",
            author="Susanna Clarke",
            finished_on=date(2025, 6, 1),
            rating=5,
        )
        MemberRating.objects.create(book=cls.book, member=cls.ada, score=5)
        MemberRating.objects.create(book=cls.book, member=cls.bob, score=4)
        MemberRating.objects.create(book=cls.book, member=cls.zoe, score=3)

    def test_the_detail_page_shows_the_average_and_every_score(self):
        response = self.client.get(
            reverse("club:history_detail", args=[self.book.pk])
        )

        self.assertContains(response, "Members averaged 4.0 out of 5")
        self.assertContains(response, "from 3")
        self.assertContains(response, "Ada — 5 out of 5")
        self.assertContains(response, "Bob — 4 out of 5")

    def test_a_departed_members_score_stays_in_the_average_with_her_name(self):
        """Decision #3: she left the roster, not the record."""
        response = self.client.get(
            reverse("club:history_detail", args=[self.book.pk])
        )

        self.assertContains(response, "Zoe — 3 out of 5")
        self.assertContains(response, "Members averaged 4.0")

    def test_the_clubs_own_rating_is_shown_as_a_separate_number(self):
        response = self.client.get(
            reverse("club:history_detail", args=[self.book.pk])
        )

        self.assertContains(response, "the club said 5 out of 5")
        self.assertContains(response, "Members averaged 4.0")

    def test_the_list_page_shows_the_average_beside_the_clubs_number(self):
        response = self.client.get(reverse("club:history"))

        self.assertContains(response, "the club said 5 out of 5")
        self.assertContains(response, "members averaged 4.0")
        self.assertContains(response, "from 3")

    def test_the_average_is_shown_to_one_decimal_place(self):
        MemberRating.objects.filter(member=self.bob).update(score=2)

        response = self.client.get(reverse("club:history"))

        self.assertContains(response, "members averaged 3.3")

    def test_a_member_who_has_rated_is_offered_a_change_rather_than_a_rating(self):
        session = self.client.session
        session["member_id"] = self.ada.pk
        session.save()

        response = self.client.get(
            reverse("club:history_detail", args=[self.book.pk])
        )

        self.assertContains(response, "Change your rating")
        self.assertNotContains(response, "Rate this book")

    def test_a_member_who_has_not_rated_is_offered_one(self):
        cleo = Member.objects.create(name="Cleo")
        session = self.client.session
        session["member_id"] = cleo.pk
        session.save()

        response = self.client.get(
            reverse("club:history_detail", args=[self.book.pk])
        )

        self.assertContains(response, "Rate this book")
        self.assertNotContains(response, "Change your rating")

    def test_the_rating_form_starts_from_the_members_own_score(self):
        session = self.client.session
        session["member_id"] = self.ada.pk
        session.save()

        response = self.client.get(
            reverse("club:history_detail", args=[self.book.pk])
        )

        self.assertEqual(response.context["my_rating"].score, 5)
        self.assertEqual(response.context["rating_form"].initial["score"], 5)
        self.assertContains(response, 'value="5" selected')

    def test_the_archive_does_not_query_once_per_book(self):
        for index in range(10):
            other = Book.objects.create(
                title=f"Book {index:02d}", author="A", finished_on=date(2024, 1, 1)
            )
            MemberRating.objects.create(book=other, member=self.ada, score=3)

        with self.assertNumQueries(1):
            response = self.client.get(reverse("club:history"))

        self.assertEqual(len(response.context["books"]), 11)


class UnratedBookTests(TestCase):
    """A finished book nobody has scored."""

    @classmethod
    def setUpTestData(cls):
        cls.book = Book.objects.create(
            title="Piranesi", author="Susanna Clarke", finished_on=date(2025, 6, 1)
        )

    def test_the_detail_page_says_so_rather_than_averaging_zero(self):
        response = self.client.get(
            reverse("club:history_detail", args=[self.book.pk])
        )

        self.assertContains(response, "Nobody has rated this one yet")
        self.assertNotContains(response, "averaged 0")

    def test_the_list_page_says_nothing_about_an_average(self):
        response = self.client.get(reverse("club:history"))

        self.assertNotContains(response, "members averaged")


class InlineRatingFormTests(TestCase):
    """The form lives on the archive page itself.

    Decision #23: the discussion on a finished book is closed and the rating is
    not, and this page is the only place a finished book lives. Sending a member
    somewhere else to type one number would be a page for the sake of a route.
    """

    @classmethod
    def setUpTestData(cls):
        cls.ada = Member.objects.create(name="Ada")
        cls.book = Book.objects.create(
            title="Piranesi", author="Susanna Clarke", finished_on=date(2025, 6, 1)
        )
        cls.current = Book.objects.create(
            title="Middlemarch", author="George Eliot", is_current=True
        )

    def setUp(self):
        session = self.client.session
        session["member_id"] = self.ada.pk
        session.save()
        self.url = reverse("club:history_detail", args=[self.book.pk])

    def test_an_identified_member_gets_a_form_on_the_archive_page(self):
        response = self.client.get(self.url)

        self.assertIsNotNone(response.context["rating_form"])
        self.assertContains(response, "<form")

    def test_the_form_posts_to_the_rating_route(self):
        response = self.client.get(self.url)

        self.assertContains(
            response,
            'action="%s"' % reverse("club:book_rate", args=[self.book.pk]),
        )

    def test_submitting_it_records_the_score_without_a_second_page(self):
        response = self.client.post(
            reverse("club:book_rate", args=[self.book.pk]),
            {"score": "4"},
            follow=True,
        )

        self.assertRedirects(response, self.url)
        self.assertEqual(MemberRating.objects.get().score, 4)
        self.assertContains(response, "Ada — 4 out of 5")

    def test_the_form_comes_back_prefilled_with_what_was_just_saved(self):
        self.client.post(
            reverse("club:book_rate", args=[self.book.pk]), {"score": "2"}
        )

        response = self.client.get(self.url)

        self.assertEqual(response.context["rating_form"].initial["score"], 2)

    def test_a_first_rating_offers_a_blank_form(self):
        response = self.client.get(self.url)

        self.assertIsNone(response.context["rating_form"].initial.get("score"))
        self.assertContains(response, "Rate this book")

    def test_an_unidentified_viewer_gets_no_form(self):
        self.client.session.flush()
        self.client.cookies.clear()

        response = self.client.get(self.url)

        self.assertIsNone(response.context["rating_form"])
        self.assertNotContains(response, "<form")

    def test_the_current_read_gets_no_form(self):
        response = self.client.get(
            reverse("club:history_detail", args=[self.current.pk])
        )

        self.assertIsNone(response.context["rating_form"])
        self.assertNotContains(response, "<form")

    def test_a_rejected_score_comes_back_on_a_page_with_a_form(self):
        """The archive page renders nothing bound, so a bad submission needs
        somewhere to land that still has the form and the error on it."""
        response = self.client.post(
            reverse("club:book_rate", args=[self.book.pk]), {"score": "9"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A rating runs from 1 to 5.")
        self.assertContains(response, "<form")
