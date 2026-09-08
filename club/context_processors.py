from .identity import current_member as resolve_current_member


def is_club_admin(request):
    """Expose the admin PIN flag to every template as `is_club_admin`.

    Always present and always a bool, so a template can branch on it without
    worrying about an absent key. It decides what the header shows; it never
    decides what a view allows — that is `club_admin_required`.
    """
    session = getattr(request, "session", None)
    return {"is_club_admin": bool(session and session.get("is_club_admin"))}


def current_member(request):
    """Expose the session's member to every template as `current_member`.

    Always present, `None` when nobody has identified — decision #4, so that no
    form anywhere has to ask who the viewer is. A session pointing at a member
    who has since been deactivated or deleted resolves to `None` and clears
    itself; see `club/identity.py`.
    """
    if getattr(request, "session", None) is None:
        return {"current_member": None}

    return {"current_member": resolve_current_member(request)}
