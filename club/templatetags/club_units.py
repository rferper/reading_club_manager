"""Template filters that print a count in whatever the book is measured in.

Thin wrappers over `Book.describe_units` and `Book.describe_change`, so the
minutes formatter (`club.duration.format_minutes`) is the one place "4h 12m" is
produced and no template ever prints a raw minute count.
"""

from django import template

register = template.Library()


@register.filter
def counted(units, book):
    """``604 pages``, ``12 chapters``, ``4h 12m``."""
    return book.describe_units(units)


@register.filter
def counted_of_total(units, book):
    """``604 of 880 pages``, ``4h 12m of 12h 30m``; no total, no ``of``."""
    return book.describe_units(units, with_total=True)


@register.filter
def signed(change, book):
    """``+293 pages``, ``-45m``, ``+1h 5m``."""
    return book.describe_change(change)
