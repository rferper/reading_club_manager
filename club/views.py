import hmac
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, models, transaction
from django.db.models import F, OuterRef, Prefetch, Subquery
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .decorators import club_admin_required, require_member
from .forms import (
    AdminPinForm,
    AnswerForm,
    BookEditForm,
    BookFinishForm,
    BookForm,
    IdentityForm,
    MemberForm,
    NoteForm,
    ProgressForm,
    QuestionForm,
)
from .identity import current_member, forget_member, remember_member
from .models import Answer, Book, Member, Note, Progress, Question


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
    """The current book's questions and everyone's answers to them.

    Reading is open to anyone. Answering needs a name, which is attribution and
    not authorisation — decision #5.
    """
    if request.method == "POST":
        return _post_answer(request)

    return _render_questions(request)


def _render_questions(request, bound_form=None):
    """Render the page, optionally with one question's form showing errors.

    Every question carries its own form. Exactly one of them can be bound —
    the question just submitted — and the rest are fresh, prefilled with this
    viewer's existing answer where there is one.
    """
    book = Book.objects.current()
    viewer = current_member(request)

    if book is None:
        return render(request, "club/questions.html", {"book": None, "rows": []})

    open_questions = book.questions.all()
    bound_question = (
        bound_form.data.get("question") if bound_form is not None else None
    )

    rows = []
    for question in open_questions.prefetch_related(
        Prefetch("answers", queryset=Answer.objects.select_related("member"))
    ):
        answers = list(question.answers.all())
        mine = next((a for a in answers if a.member_id == getattr(viewer, "pk", None)), None)

        if bound_form is not None and str(question.pk) == bound_question:
            form = bound_form
        else:
            form = AnswerForm(
                questions=open_questions,
                initial={"question": question, "body": mine.body if mine else ""},
            )

        rows.append(
            {"question": question, "answers": answers, "mine": mine, "form": form}
        )

    return render(request, "club/questions.html", {"book": book, "rows": rows})


@require_member
def _post_answer(request):
    """Record this member's answer, replacing their previous one.

    Not routed: `questions` dispatches here on POST. `update_or_create` is what
    decision #6 asks for — one row per member per question, edited in place, so
    changing your mind is an update rather than an integrity error.
    """
    book = Book.objects.current()

    if book is None:
        messages.error(request, "There is no current book to discuss.")
        return redirect("club:home")

    form = AnswerForm(request.POST, questions=book.questions.all())

    if not form.is_valid():
        return _render_questions(request, bound_form=form)

    Answer.objects.update_or_create(
        question=form.cleaned_data["question"],
        member=current_member(request),
        defaults={"body": form.cleaned_data["body"]},
    )

    messages.success(request, "Answer saved.")
    return redirect("club:questions")


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


def history(request):
    """Every book that is not the club's current read, newest finished first.

    Uncapped, and staying that way — a club reads a dozen books a year, and
    #20 holds search and pagination for whenever that stops being true.
    """
    return render(
        request,
        "club/history.html",
        {"books": Book.objects.filter(is_current=False)},
    )


def history_detail(request, pk):
    """One book's discussion, replayed read-only.

    This works because notes, questions and answers carried a book foreign key
    from the start (decision #8) rather than being scoped to whatever happened
    to be current. Nothing here writes, and nothing here is offered to write.
    """
    book = get_object_or_404(Book, pk=pk)

    return render(
        request,
        "club/history_detail.html",
        {
            "book": book,
            "notes": book.notes.select_related("author"),
            "questions": book.questions.prefetch_related(
                Prefetch("answers", queryset=Answer.objects.select_related("member"))
            ),
            "progress": book.progress.select_related("member"),
        },
    )


@club_admin_required
def book_start(request):
    """Make a new book the club's current read."""
    current = Book.objects.current()

    if current is not None:
        messages.error(
            request,
            f"The club is already reading {current.title}. Finish that one first.",
        )
        return redirect("club:home")

    form = BookForm(
        request.POST or None, initial={"started_on": timezone.localdate()}
    )

    if request.method == "POST" and form.is_valid():
        book = form.save(commit=False)
        book.is_current = True

        try:
            with transaction.atomic():
                book.save()
        except IntegrityError:
            # The check above is not a lock. Two admins starting a book at once
            # is far-fetched, but the constraint is real and this is the
            # difference between a sentence and a debug page.
            form.add_error(
                None, "Another book became the current read while you were typing."
            )
        else:
            messages.success(request, f"{book.title} is the club's book now.")
            return redirect("club:home")

    return render(
        request,
        "club/book_form.html",
        {"form": form, "heading": "Start a book", "submit_label": "Start reading"},
    )


@club_admin_required
def book_finish(request, pk):
    """Record the finish date and rating, and clear the current-read flag.

    Nothing moves and nothing is deleted — decision #2. Every progress row,
    note, question and answer keeps pointing at this same row, which is the
    entire reason the flag exists instead of two tables.
    """
    book = get_object_or_404(Book, pk=pk, is_current=True)
    form = BookFinishForm(
        request.POST or None,
        instance=book,
        initial={"finished_on": timezone.localdate()},
    )

    if request.method == "POST" and form.is_valid():
        finished = form.save(commit=False)
        finished.is_current = False
        finished.save()
        messages.success(
            request,
            f"{finished.title} is in the archive, discussion and all.",
        )
        return redirect("club:history_detail", pk=finished.pk)

    return render(request, "club/book_finish.html", {"form": form, "book": book})


@club_admin_required
def book_edit(request, pk):
    """Correct a book's metadata, current or archived.

    Not the current-read flag: that moves through starting and finishing, which
    is where the rule about there being one of them lives.
    """
    book = get_object_or_404(Book, pk=pk)
    form = BookEditForm(request.POST or None, instance=book)

    if request.method == "POST" and form.is_valid():
        book = form.save()
        messages.success(request, f"{book.title} is updated.")
        if book.is_current:
            return redirect("club:home")
        return redirect("club:history_detail", pk=book.pk)

    return render(
        request,
        "club/book_form.html",
        {
            "form": form,
            "book": book,
            "heading": f"Edit {book.title}",
            "submit_label": "Save changes",
        },
    )
