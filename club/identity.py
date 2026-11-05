"""Who the session says the viewer is.

Decision #4: a viewer picks their name once and it reaches every template as
`current_member`, so no individual form carries a "who are you" field.

Decision #5: anyone may pick anyone. This is a convenience for attribution, not
a boundary, and nothing may be built on top of it that assumes otherwise.

The session key is `member_id`, which is the key
`_docs/testing-guidelines.md` already tells tests to write directly.
"""

from django.conf import settings
from django.utils import timezone

from .models import Member

SESSION_KEY = "member_id"

# Admin mode (decision #33). The flag says the PIN was typed; the two
# timestamps (epoch seconds) say when admin mode began and when it was last
# used, so it can lapse on idle time or total age. Hygiene, not security
# (decision #5).
ADMIN_KEY = "is_club_admin"
ADMIN_STARTED_KEY = "club_admin_started_at"
ADMIN_LAST_USED_KEY = "club_admin_last_used_at"

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


def _admin_now():
    return timezone.now().timestamp()


def _clear_admin(session):
    for key in (ADMIN_KEY, ADMIN_STARTED_KEY, ADMIN_LAST_USED_KEY):
        session.pop(key, None)


def is_admin(request):
    """Is this request in admin mode? The only code that reads the raw flag.

    False, and the flag plus both timestamps removed, when the session has been
    idle longer than `CLUB_ADMIN_IDLE_SECONDS` or admin mode is older than
    `CLUB_ADMIN_MAX_SECONDS`. A flag with missing or unreadable timestamps counts
    as expired. A request that passes moves the last-used timestamp forward.
    `member_id` is never touched. Decision #33.
    """
    session = getattr(request, "session", None)
    if session is None or not session.get(ADMIN_KEY):
        return False

    now = _admin_now()
    started = session.get(ADMIN_STARTED_KEY)
    last_used = session.get(ADMIN_LAST_USED_KEY)

    valid = (
        isinstance(started, (int, float))
        and isinstance(last_used, (int, float))
        and now - last_used <= settings.CLUB_ADMIN_IDLE_SECONDS
        and now - started <= settings.CLUB_ADMIN_MAX_SECONDS
    )
    if not valid:
        _clear_admin(session)
        return False

    session[ADMIN_LAST_USED_KEY] = now
    return True


def begin_admin(request):
    """Enter admin mode after a correct PIN, rotating the session key."""
    request.session.cycle_key()
    now = _admin_now()
    request.session[ADMIN_KEY] = True
    request.session[ADMIN_STARTED_KEY] = now
    request.session[ADMIN_LAST_USED_KEY] = now


def end_admin(request):
    """Leave admin mode. Safe when it was not on."""
    _clear_admin(request.session)
