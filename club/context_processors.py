def is_club_admin(request):
    """Expose the admin PIN flag to every template as `is_club_admin`.

    Always present and always a bool, so a template can branch on it without
    worrying about an absent key. It decides what the header shows; it never
    decides what a view allows — that is `club_admin_required`.
    """
    session = getattr(request, "session", None)
    return {"is_club_admin": bool(session and session.get("is_club_admin"))}
