"""Listening time: one parser for what people type, one formatter for what they read.

Minutes are the stored unit (decision #34). Nothing here knows about models;
the form field at the bottom is the only Django-facing part, so the same
input format serves the book form, the progress form and the admin.
"""

import re

from django import forms
from django.core.exceptions import ValidationError

EXAMPLE = 'Try something like "4h 12m", "4h", "90m" or "4:12".'

_HOURS_AND_MINUTES = re.compile(r"(\d+)\s*h(?:\s*(\d+)\s*m)?")
_MINUTES_ONLY = re.compile(r"(\d+)\s*m")
_CLOCK = re.compile(r"(\d+):(\d{2})")


def parse_minutes(text):
    """Whole minutes for ``text`` such as ``4h 12m``, or a ValidationError.

    Accepted: ``4h 12m``, ``4h``, ``12m``, ``90m``, ``4:12``, in any case and
    with spaces around or inside. A bare ``0`` is accepted as zero. Minutes of
    60 or more are refused only when hours are also given (``1h 75m``);
    ``75m`` alone is fine. Decimals, negatives and prose are refused with an
    example in the message.
    """
    cleaned = (text or "").strip().lower()

    # The page caps the input at 20 characters, but a hand-made POST is not
    # held to that, and `int()` raises ValueError (a 500) past 4300 digits.
    if len(cleaned) > 20:
        raise ValidationError(f"That is too long for a length of time. {EXAMPLE}")

    if cleaned == "0":
        return 0

    if match := _HOURS_AND_MINUTES.fullmatch(cleaned):
        hours, minutes = int(match.group(1)), match.group(2)
        minutes = int(minutes) if minutes is not None else 0
    elif match := _MINUTES_ONLY.fullmatch(cleaned):
        return int(match.group(1))
    elif match := _CLOCK.fullmatch(cleaned):
        hours, minutes = int(match.group(1)), int(match.group(2))
    else:
        raise ValidationError(f"That does not look like a length of time. {EXAMPLE}")

    if minutes >= 60:
        raise ValidationError(
            f"Give minutes as under 60 when hours are given, or use minutes "
            f'alone (for example "{hours * 60 + minutes}m"). {EXAMPLE}'
        )

    return hours * 60 + minutes


def format_minutes(minutes):
    """``252`` -> ``4h 12m``; ``180`` -> ``3h``; ``45`` -> ``45m``; ``0`` -> ``0m``."""
    hours, rest = divmod(minutes, 60)

    if hours and rest:
        return f"{hours}h {rest}m"

    if hours:
        return f"{hours}h"

    return f"{rest}m"


class MinutesField(forms.CharField):
    """A text input that cleans to whole minutes and redisplays as ``Xh Ym``.

    ``allow_zero=False`` is for a book's total, where zero is a typo
    (decision #24); a member's own progress may be a recorded zero.
    """

    def __init__(self, *, allow_zero=True, **kwargs):
        self.allow_zero = allow_zero
        # No `max_length`: its validator would call `len()` on the cleaned int.
        super().__init__(**kwargs)
        self.widget.attrs.setdefault("maxlength", 20)

    def prepare_value(self, value):
        if isinstance(value, int):
            return format_minutes(value)

        return value

    def to_python(self, value):
        value = super().to_python(value)

        if value in self.empty_values:
            return None

        minutes = parse_minutes(value)

        if minutes == 0 and not self.allow_zero:
            raise ValidationError(f"A length of time must be more than zero. {EXAMPLE}")

        return minutes
