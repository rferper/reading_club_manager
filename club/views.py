import hmac
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import models
from django.db.models import F, OuterRef, Subquery
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .decorators import club_admin_required, require_member
from .forms import (
    AdminPinForm,
    IdentityForm,
    MemberForm,
    NoteForm,
    ProgressForm,
    QuestionForm,
)
from .identity import current_member, forget_member, remember_member
from .models import Book, Member, Note, Progress, Question


def home(request):
    """The club's landing page: what we are reading right now.

    Between reads is a legitimate state (decision #2), so `current()` answering
    None is the empty state and not an error.
    """
    return render(request, "club/home.html", {"book": Book.objects.current()})


def _safe_next(request, next_url):
    """The submitted `next`, or None when it cannot be trusted.

    Rejects anything pointing off this host or scheme, and the gate pages
    themselves, so a bookmarked or hand-edited `?next=` cannot bounce a gate
    back to itself or straight out through its own exit route.
    """
    if not next_url:
        return None

    if not url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return None

    gates = {
        reverse("club:admin_pin"),
        reverse("club:admin_exit"),
        reverse("club:identify"),
        reverse("club:forget_me"),
    }
    if urlsplit(next_url).path in gates:
        return None

    return next_url


def admin_pin(request):
    """Enter the shared PIN to turn on admin mode for this session.

    The PIN is not security — decision #5. It stops a member wandering into the
    history editor by accident, and nothing else.
    """
    next_url = _safe_next(request, request.POST.get("next") or request.GET.get("next"))
    destination = next_url or reverse("club:home")

    # `CLUB_ADMIN_PIN=` in the environment resolves to "", not to the
    # documented default, so this asks the resolved setting rather than whether
    # the variable was set. A blank PIN fails closed: admin mode is unreachable.
    pin_configured = bool(settings.CLUB_ADMIN_PIN)

    if request.session.get("is_club_admin"):
        return redirect(destination)

    form = AdminPinForm()

    if request.method == "POST" and pin_configured:
        form = AdminPinForm(request.POST)
        if form.is_valid():
            # Encoded bytes: compare_digest raises TypeError on a non-ASCII
            # str, so an accented PIN would otherwise 500 rather than refuse.
            submitted = form.cleaned_data["pin"].encode()
            if hmac.compare_digest(submitted, settings.CLUB_ADMIN_PIN.encode()):
                request.session["is_club_admin"] = True
                messages.success(request, "Admin mode is on.")
                return redirect(destination)
            form.add_error("pin", "That PIN is not right.")

    return render(
        request,
        "club/admin_pin.html",
        {
            "form": form,
            "pin_configured": pin_configured,
            "next": next_url or "",
        },
    )


@require_POST
@club_admin_required
def admin_exit(request):
    """Leave admin mode.

    `require_POST` is outermost on purpose: a GET is a 405 whatever the session
    holds, so the route never answers a state change to a link.
    """
    request.session.pop("is_club_admin", None)
    messages.success(request, "Admin mode is off.")
    return redirect("club:home")


def member_list(request):
    """The roster, readable by anyone.

    Deactivated members stay on this page and stay marked (decision #3): they
    left the club, not the record.
    """
    return render(
        request,
        "club/member_list.html",
        {"members": Member.objects.all()},
    )


@club_admin_required
def member_add(request):
    """Put someone new on the roster."""
    form = MemberForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        member = form.save()
        messages.success(request, f"{member.name} is on the roster.")
        return redirect("club:member_list")

    return render(
        request,
        "club/member_form.html",
        {
            "form": form,
            "heading": "Add a member",
            "submit_label": "Add member",
        },
    )


@club_admin_required
def member_edit(request, pk):
    """Rename a member, or change the label their role is."""
    member = get_object_or_404(Member, pk=pk)
    form = MemberForm(request.POST or None, instance=member)

    if request.method == "POST" and form.is_valid():
        member = form.save()
        messages.success(request, f"{member.name} is updated.")
        return redirect("club:member_list")

    return render(
        request,
        "club/member_form.html",
        {
            "form": form,
            "member": member,
            "heading": f"Edit {member.name}",
            "submit_label": "Save changes",
        },
    )


@require_POST
@club_admin_required
def member_toggle(request, pk):
    """Deactivate a member, or bring them back.

    There is no delete, now or later — decision #3. `require_POST` is outermost
    so a GET is a 405 whatever the session holds, and nothing that changes the
    roster can hide behind a link.
    """
    member = get_object_or_404(Member, pk=pk)
    member.is_active = not member.is_active
    member.save(update_fields=["is_active"])

    if member.is_active:
        messages.success(request, f"{member.name} is reading with the club again.")
    else:
        messages.success(request, f"{member.name} is no longer on the active roster.")

    return redirect("club:member_list")


def identify(request):
    """Say which member you are, once, for the rest of the session.

    There is no password and there is not going to be one — decision #5.
    Anyone may pick anyone; what this buys is a name on every note and answer
    without any form having to ask for one.
    """
    next_url = _safe_next(request, request.POST.get("next") or request.GET.get("next"))
    destination = next_url or reverse("club:home")

    viewer = current_member(request)
    form = IdentityForm(
        request.POST or None,
        initial={"member": viewer} if viewer else None,
    )

    if request.method == "POST" and form.is_valid():
        member = form.cleaned_data["member"]
        remember_member(request, member)
        messages.success(request, f"You are {member.name}.")
        return redirect(destination)

    return render(
        request,
        "club/identify.html",
        {
            "form": form,
            "next": next_url or "",
            "roster_is_empty": not Member.objects.filter(is_active=True).exists(),
        },
    )


@require_POST
def forget_me(request):
    """Stop being anybody in particular.

    Not gated on being identified: clearing a key that is already absent is
    the outcome the caller wanted either way.
    """
    forget_member(request)
    messages.success(request, "Forgotten — pick a name again whenever you like.")
    return redirect("club:home")


@require_member
def progress_update(request):
    """Record how far you have read the current book.

    The member comes from the session, never from the form — decision #4. GET
    renders the form so an unidentified visitor is sent to the picker and
    returned here; POST saves and redirects, so a refresh cannot resubmit.
    """
    book = Book.objects.current()

    if book is None:
        messages.error(
            request, "There is no current book, so there is nothing to record yet."
        )
        return redirect("club:home")

    member = current_member(request)

    # Deliberately not `get_or_create`: a GET must not write a row. A member who
    # opens the form and closes it again has recorded nothing, and #10 shows
    # them as zero either way.
    progress = Progress.objects.filter(book=book, member=member).first() or Progress(
        book=book, member=member
    )
    form = ProgressForm(request.POST or None, instance=progress, book=book)

    if request.method == "POST" and form.is_valid():
        progress = form.save()
        if progress.percent is None:
            messages.success(request, f"You are {progress.pages_read} pages in.")
        else:
            messages.success(
                request,
                f"You are {progress.pages_read} pages in — {progress.percent}%.",
            )
        return redirect("club:home")

    return render(
        request,
        "club/progress_form.html",
        {"form": form, "book": book, "progress": progress},
    )


def progress_overview(request):
    """Who is ahead and who is behind on the current book.

    One query for the roster, whatever its size: each active member is
    annotated with their own `pages_read` through a subquery rather than
    walking `member.progress` per row. `assertNumQueries` pins that.

    A member with nothing recorded is annotated `None`, which is not the same
    as a recorded zero — the page says "not started" for one and "0 pages" for
    the other — but both sort to the bottom and neither is left out.
    """
    book = Book.objects.current()
    rows = []

    if book is not None:
        members = (
            Member.objects.filter(is_active=True)
            .annotate(
                recorded_pages=Subquery(
                    Progress.objects.filter(
                        member=OuterRef("pk"), book=book
                    ).values("pages_read")[:1]
                )
            )
            .order_by(F("recorded_pages").desc(nulls_last=True), Lower("name"))
        )

        rows = [
            {
                "member": member,
                "pages_read": member.recorded_pages or 0,
                "percent": book.percent_of(member.recorded_pages or 0),
                "has_recorded": member.recorded_pages is not None,
            }
            for member in members
        ]

    return render(
        request,
        "club/progress.html",
        {"book": book, "rows": rows},
    )


def notes(request):
    """Notes on the current book, newest first, plus the form to add one.

    Reading is open to anyone. Posting needs a name, which is attribution and
    not authorisation — decision #5.
    """
    if request.method == "POST":
        return _post_note(request)

    return _render_notes(request, NoteForm())


def _render_notes(request, form):
    book = Book.objects.current()
    viewer = current_member(request)
    is_admin = bool(request.session.get("is_club_admin"))

    # Each note is paired with whether this viewer may remove it, asked of the
    # model rather than re-derived in the template. The button is decoration
    # either way — `note_delete` asks the same question again.
    rows = [
        {"note": note, "may_remove": note.may_be_removed_by(viewer, is_admin)}
        for note in (book.notes.select_related("author") if book else [])
    ]

    return render(
        request,
        "club/notes.html",
        {"book": book, "rows": rows, "form": form},
    )


@require_member
def _post_note(request):
    """Post a note as the session's member.

    Not routed: `notes` dispatches here on POST. The decorator does the
    refusing, so an unidentified POST is a 403 rather than a redirect that
    would drop what the member typed — decision #16.
    """
    book = Book.objects.current()

    if book is None:
        messages.error(request, "There is no current book to write about.")
        return redirect("club:home")

    form = NoteForm(request.POST)

    if not form.is_valid():
        return _render_notes(request, form)

    note = form.save(commit=False)
    note.book = book
    note.author = current_member(request)
    note.save()

    messages.success(request, "Note posted.")
    return redirect("club:notes")


@require_POST
def note_delete(request, pk):
    """Remove a note — its author, or an admin. Decision #7.

    A 403 rather than a redirect, because a member acting on somebody else's
    note is a real refusal and not a missing step.
    """
    note = get_object_or_404(Note, pk=pk)

    if not note.may_be_removed_by(
        current_member(request), request.session.get("is_club_admin")
    ):
        raise PermissionDenied("A note is removed by the member who wrote it.")

    note.delete()
    messages.success(request, "Note removed.")
    return redirect("club:notes")


def questions(request):
    """The current book's discussion questions, in the admin's order.

    Readable by anyone. #13 adds the answers and the form to submit one.
    """
    book = Book.objects.current()

    return render(
        request,
        "club/questions.html",
        {"book": book, "questions": book.questions.all() if book else []},
    )


@club_admin_required
def question_add(request):
    """Post a discussion question against the current book."""
    book = Book.objects.current()

    if book is None:
        messages.error(request, "There is no current book to ask about.")
        return redirect("club:home")

    last = book.questions.aggregate(models.Max("position"))["position__max"] or 0
    form = QuestionForm(request.POST or None, initial={"position": last + 1})

    if request.method == "POST" and form.is_valid():
        question = form.save(commit=False)
        question.book = book
        question.save()
        messages.success(request, "Question posted.")
        return redirect("club:questions")

    return render(
        request,
        "club/question_form.html",
        {
            "form": form,
            "book": book,
            "heading": "Add a question",
            "submit_label": "Post question",
        },
    )


@club_admin_required
def question_edit(request, pk):
    """Reword a question, or move it in the sequence."""
    question = get_object_or_404(Question, pk=pk)
    form = QuestionForm(request.POST or None, instance=question)

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Question updated.")
        return redirect("club:questions")

    return render(
        request,
        "club/question_form.html",
        {
            "form": form,
            "book": question.book,
            "question": question,
            "heading": "Edit a question",
            "submit_label": "Save changes",
        },
    )


@club_admin_required
def question_delete(request, pk):
    """Remove a question, and every answer to it.

    GET renders the confirmation — the one thing a GET may do here — and the
    removal happens on POST. The confirmation says what goes with it, because
    the answers are other people's writing and the admin cannot see them from
    the button.
    """
    question = get_object_or_404(Question, pk=pk)

    if request.method == "POST":
        question.delete()
        messages.success(request, "Question removed, along with its answers.")
        return redirect("club:questions")

    return render(request, "club/question_confirm_delete.html", {"question": question})
