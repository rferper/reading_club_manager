from functools import wraps
from urllib.parse import urlencode

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse

from .identity import current_member


def _refuse(request, gate_url_name, reason):
    """One refusal rule, shared by both gates in this app.

    The refusal splits on method, because a redirect answers a POST with a GET
    and silently discards the payload:

    - GET or HEAD redirects to the gate with `?next=` back to here, which is
      the missing step it looks like.
    - Anything else, POST included, raises `PermissionDenied` for a 403. The
      submitted data is lost either way; a 403 at least says so, where an
      automated POST would read a 302 as success. It is also the only workable
      answer for a POST-only route: sending `?next=/progress/update/` through
      the gate would land the viewer back on that URL as a GET, which is a 405.

    No Django message is added on either path: the gate page explains itself,
    and a bare `RequestFactory` request has no message storage.
    """
    if request.method in ("GET", "HEAD"):
        query = urlencode({"next": request.get_full_path()})
        return redirect(f"{reverse(gate_url_name)}?{query}")

    raise PermissionDenied(reason)


def club_admin_required(view_func):
    """Refuse a view to anyone without the admin PIN flag in their session."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.session.get("is_club_admin"):
            return view_func(request, *args, **kwargs)

        return _refuse(
            request, "club:admin_pin", "Admin mode is required for this action."
        )

    return wrapper


def require_member(view_func):
    """Refuse a view to anyone who has not said which member they are.

    Attribution, not authorisation — decision #5. It stops a note being filed
    against nobody, and it stops nothing else.
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if current_member(request) is not None:
            return view_func(request, *args, **kwargs)

        return _refuse(
            request, "club:identify", "Pick your name before posting as somebody."
        )

    return wrapper
