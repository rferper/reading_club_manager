"""Listening time: the parser, the formatter and the form field (decision #34)."""

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from ..duration import MinutesField, format_minutes, parse_minutes


class ParseMinutesTests(SimpleTestCase):
    def test_every_accepted_form_gives_the_right_minutes(self):
        accepted = {
            "4h 12m": 252,
            "4h": 240,
            "12m": 12,
            "90m": 90,
            "4:12": 252,
            "4H 12M": 252,
            "  4h 12m  ": 252,
            "4h12m": 252,
            "4 h 12 m": 252,
            "75m": 75,
            "0": 0,
            "0m": 0,
            "0h": 0,
            "0:00": 0,
            "12:30": 750,
        }
        for text, minutes in accepted.items():
            with self.subTest(text=text):
                self.assertEqual(parse_minutes(text), minutes)

    def test_every_rejected_form_gives_an_error_with_an_example(self):
        rejected = [
            "",
            "   ",
            "soon",
            "4.5h",
            "1.5",
            "-5m",
            "-1h",
            "1h 75m",
            "2h 60m",
            "4:75",
            "4:5",
            "12",
            "4 hours",
            "h",
            "m",
        ]
        for text in rejected:
            with self.subTest(text=text):
                with self.assertRaises(ValidationError) as caught:
                    parse_minutes(text)

                self.assertIn("4h 12m", caught.exception.messages[0])


class FormatMinutesTests(SimpleTestCase):
    def test_hours_and_minutes_read_as_the_issue_says(self):
        for minutes, text in {
            252: "4h 12m",
            180: "3h",
            45: "45m",
            0: "0m",
            60: "1h",
            61: "1h 1m",
            750: "12h 30m",
        }.items():
            with self.subTest(minutes=minutes):
                self.assertEqual(format_minutes(minutes), text)


class MinutesFieldTests(SimpleTestCase):
    def test_it_cleans_to_whole_minutes(self):
        self.assertEqual(MinutesField().clean("4h 12m"), 252)

    def test_it_redisplays_stored_minutes_as_time(self):
        self.assertEqual(MinutesField().prepare_value(252), "4h 12m")

    def test_zero_is_refused_where_zero_is_not_allowed(self):
        with self.assertRaises(ValidationError):
            MinutesField(allow_zero=False).clean("0")

    def test_zero_is_a_recorded_value_where_it_is_allowed(self):
        self.assertEqual(MinutesField().clean("0"), 0)

    def test_blank_is_none_when_not_required(self):
        self.assertIsNone(MinutesField(required=False).clean(""))
