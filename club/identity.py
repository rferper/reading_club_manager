"""Who the session says the viewer is.

Decision #4: a viewer picks their name once and it reaches every template as
`current_member`, so no individual form carries a "who are you" field.

Decision #5: anyone may pick anyone. This is a convenience for attribution, not
a boundary, and nothing may be built on top of it that assumes otherwise.

The session key is `member_id`, which is the key
`_docs/testing-guidelines.md` already tells tests to write directly.
"""

from .models import Member

SESSION_KEY = "member_id"

# `None` is a real answer here — nobody has identified — so the "not looked up
# yet" state needs a value of its own.
_UNRESOLVED = object()


def current_member(request):
    """The active `Member` this session points at, or `None`.

    A session holding the id of someone since deactivated or deleted clears
    itself rather than raising. Their row going away does not make the viewer's
    next page load an error; it makes them unidentified, and the picker is one
    click.

    Resolved once per request and cached on it, because the context processor
    and `require_member` both ask on the same request.
    """
    cached = getattr(request, "_current_member", _UNRESOLVED)
    if cached is not _UNRESOLVED:
        return cached

    member = None
    member_id = request.session.get(SESSION_KEY)

    if member_id is not None:
        member = Member.objects.filter(pk=member_id, is_active=True).first()
        if member is None:
            forget_member(request)

    request._current_member = member
    return member


def remember_member(request, member):
    """Record this member as the viewer, for the life of the session."""
    request.session[SESSION_KEY] = member.pk
    request._current_member = member


def forget_member(request):
    """Stop being anybody. Safe to call when nobody was identified."""
    request.session.pop(SESSION_KEY, None)
    request._current_member = None
