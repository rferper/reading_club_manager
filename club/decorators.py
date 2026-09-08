from functools import wraps
from urllib.parse import urlencode

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse


def club_admin_required(view_func):
    """Refuse a view to anyone without the admin PIN flag in their session.

    The refusal splits on method, because a redirect answers a POST with a GET
    and silently discards the payload:

    - GET or HEAD redirects to the PIN form with `?next=` back to here, which
      is the missing step it looks like.
    - Anything else, POST included, raises `PermissionDenied` for a 403. The
      typed data is lost either way; a 403 at least says so, where an automated
      POST would read a 302 as success.

    No Django message is added on either path: the PIN page explains itself,
    and a bare `RequestFactory` request has no message storage.
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.session.get("is_club_admin"):
            return view_func(request, *args, **kwargs)

        if request.method in ("GET", "HEAD"):
            query = urlencode({"next": request.get_full_path()})
            return redirect(f"{reverse('club:admin_pin')}?{query}")

        raise PermissionDenied("Admin mode is required for this action.")

    return wrapper
