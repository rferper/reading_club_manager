"""Shared test helpers. Not a test module: the runner only collects test*.py."""

from ..identity import ADMIN_KEY, ADMIN_LAST_USED_KEY, ADMIN_STARTED_KEY, _admin_now


def enter_admin(session):
    """Put a session in admin mode the way a correct PIN would, without
    posting the form. Sets the flag and both timestamps (decision #33), because
    a bare flag now counts as expired. The caller still calls `session.save()`.
    """
    now = _admin_now()
    session[ADMIN_KEY] = True
    session[ADMIN_STARTED_KEY] = now
    session[ADMIN_LAST_USED_KEY] = now
