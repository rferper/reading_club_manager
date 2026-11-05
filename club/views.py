import datetime
import hmac
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, models, transaction
from django.db.models import Avg, Count, F, OuterRef, Prefetch, Q, Subquery
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from .decorators import club_admin_required, require_member
from .forms import (
    AdminPinForm,
    AnswerForm,
    AnswerReplyForm,
    BookEditForm,
    BookFinishForm,
    BookForm,
    IdentityForm,
    MemberForm,
    MemberRatingForm,
    NoteForm,
    ReplyForm,
    ProgressForm,
    QuestionForm,
)
from .identity import (
    begin_admin,
    current_member,
    end_admin,
    forget_member,
    is_admin,
    remember_member,
)
from .models import (
    MEASURE_LABELS,
    Answer,
    AnswerReply,
    Book,
    Member,
    MemberRating,
    Note,
    Progress,
    ProgressEntry,
    Question,
    Reaction,
)


def home(request):
    """The club's landing page: what we are reading right now.

    Between reads is a legitimate state (decision #2), so `current()` answering
    None is the empty state and not an error.
    """
    book = Book.objects.current()
    return render(
        request,
        "club/home.html",
        {"book": book, "whats_new": _whats_new(book, current_member(request))},
    )


def _whats_new(book, member):
    """What happened on the current book since `member` last looked, or None.

    None means there is nothing to show: no book, nobody identified, or nothing
    new. The marker is `notifications_seen_at`, or the start of `joined_on`
    when it is null (decision #31). Answers use `created_on`, so editing one
    later does not bring it back, and the member's own never count. Notes,
    note replies and answer replies are other members' only, counted the same way.
    """
    if book is None or member is None:
        return None

    since = member.notifications_seen_at
    if since is None:
        since = timezone.make_aware(
            datetime.datetime.combine(member.joined_on, datetime.time.min)
        )

    new_questions = list(book.questions.filter(created_on__gt=since))
    new_answers = (
        Answer.objects.filter(question__book=book, created_on__gt=since)
        .exclude(member=member)
        .count()
    )
    # One query for both counts: other members' new top-level notes and new
    # note replies on this book (#40).
    new_notes = (
        Note.objects.filter(book=book, created_on__gt=since)
        .exclude(author=member)
        .aggregate(
            notes=Count("pk", filter=Q(parent__isnull=True)),
            replies=Count("pk", filter=Q(parent__isnull=False)),
        )
    )
    # Replies to answers live in their own model (decision 43), so they take
    # one more count rather than joining the aggregate above (#60).
    new_answer_replies = (
        AnswerReply.objects.filter(
            answer__question__book=book, created_on__gt=since
        )
        .exclude(author=member)
        .count()
    )
    book_is_new = book.created_on > since

    if not (
        new_questions
        or new_answers
        or book_is_new
        or new_notes["notes"]
        or new_notes["replies"]
        or new_answer_replies
    ):
        return None

    return {
        "questions": new_questions,
        "answer_count": new_answers,
        "new_book": book if book_is_new else None,
        "note_count": new_notes["notes"],
        "reply_count": new_notes["replies"],
        "answer_reply_count": new_answer_replies,
    }


@require_POST
def mark_seen(request):
    """Stamp the viewer's marker so the home panel clears.

    Not gated with `require_member`: with nobody identified there is nothing to
    stamp, and the caller wanted the panel gone either way, so it quietly
    redirects. This is the only place the marker is ever written.
    """
    member = current_member(request)
    if member is not None:
        member.notifications_seen_at = timezone.now()
        member.save(update_fields=["notifications_seen_at"])
    return redirect("club:home")


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

    if is_admin(request):
        return redirect(destination)

    form = AdminPinForm()

    if request.method == "POST" and pin_configured:
        form = AdminPinForm(request.POST)
        if form.is_valid():
            # Encoded bytes: compare_digest raises TypeError on a non-ASCII
            # str, so an accented PIN would otherwise 500 rather than refuse.
            submitted = form.cleaned_data["pin"].encode()
            if hmac.compare_digest(submitted, settings.CLUB_ADMIN_PIN.encode()):
                begin_admin(request)
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
    end_admin(request)
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
    form = MemberForm(request.POST if request.method == "POST" else None)

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
    form = MemberForm(request.POST if request.method == "POST" else None, instance=member)

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
        request.POST if request.method == "POST" else None,
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

    A successful POST also appends a `ProgressEntry`, which is how the trail
    on `progress_trail` gets its dots. The GET still writes neither of them
    (decision #18).
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
    form = ProgressForm(request.POST if request.method == "POST" else None, instance=progress, book=book)

    if request.method == "POST" and form.is_valid():
        # `commit=False` and then `record()`, because saving the row and
        # appending the entry that dates it are one act (decision #26).
        # `Progress.record()` is the one place both writes happen, inside one
        # transaction, so the row and the newest entry cannot drift apart.
        progress = form.save(commit=False)
        progress.record()
        # Never a bare count: the unit is part of the sentence, because "12"
        # means nothing on a book measured in chapters or in anything else.
        # Minutes are said as time ("4h 12m"), never as a raw count.
        counted = f"You are {book.describe_units(progress.units_read)} in"
        if progress.percent is None:
            messages.success(request, f"{counted}.")
        else:
            messages.success(request, f"{counted} — {progress.percent}%.")
        return redirect("club:home")

    return render(
        request,
        "club/progress_form.html",
        {"form": form, "book": book, "progress": progress},
    )


# How far back "this week" on the overview reaches (decision #41). One named
# constant: not a setting, a form field or a query parameter. #53 may revise it.
RECENT_DAYS = 7


def _movement(book, member):
    """What the "This week" cell says for one annotated member, or ``None``.

    ``None`` when there is nothing to say: nothing recorded in the book's
    unit, or a count with no in-unit entry behind it (an admin edit leaves no
    dot - #51). Otherwise a ``(kind, text)`` pair: ``"first"`` when the only
    in-unit entry is inside the window, ``"same"`` when the count is where the
    baseline left it, ``"change"`` with the signed text. The baseline is the
    newest entry at or before the window start, else the oldest inside it.
    The percentage is `Book.percent_of()` on both ends, as percentage points,
    and is left out when the book has no total or the points did not move.
    """
    if member.recorded_units is None:
        return None

    baseline = member.baseline_before
    if baseline is None:
        baseline = member.baseline_inside

    if baseline is None:
        return None

    if member.baseline_before is None and member.entry_count == 1:
        return {"kind": "first", "text": "first entry this week"}

    change = member.recorded_units - baseline
    if change == 0:
        return {"kind": "same", "text": "no change this week"}

    text = book.describe_change(change)
    points = None
    if book.percent_of(baseline) is not None:
        points = book.percent_of(member.recorded_units) - book.percent_of(baseline)
    if points:
        text += f", {'+' if points > 0 else '-'}{abs(points)}%"

    return {"kind": "change", "text": text}


def progress_overview(request):
    """Who is ahead and who is behind on the current book.

    One query for the roster, whatever its size: each active member is
    annotated with their own count through a subquery rather than walking
    `member.progress` per row. `assertNumQueries` pins that.

    The subquery selects the column this book is measured in (#17), which is
    one column either way — not a second query, and not a property asked per
    row. A member whose only recorded number is in the other column reads as
    not started, which is the truth: nobody has said how far they are in the
    unit the club is now counting.

    A member with nothing recorded is annotated `None`, which is not the same
    as a recorded zero — the page says "not started" for one and "0 of 880
    pages" for the other — but both sort to the bottom and neither is left out.

    The "This week" cell (#32, decision #41) is three more correlated
    subqueries on the same roster query, over the member's in-unit
    `ProgressEntry` rows: the newest entry at or before the window start, the
    oldest one inside it, and how many in-unit entries there are. Still two
    queries for the page, whatever the roster or the length of any trail.
    """
    book = Book.objects.current()
    rows = []

    if book is not None:
        unit_column = book.unit_column
        window_start = timezone.now() - datetime.timedelta(days=RECENT_DAYS)
        # Only entries in the unit the book is counted in now (decision #27);
        # the rest are ignored, never converted.
        entries = ProgressEntry.objects.filter(
            progress__member=OuterRef("pk"),
            progress__book=book,
            **{f"{unit_column}__isnull": False},
        )
        members = (
            Member.objects.filter(is_active=True)
            .annotate(
                recorded_units=Subquery(
                    Progress.objects.filter(member=OuterRef("pk"), book=book)
                    # `Progress.Meta.ordering` joins to the book to decide what
                    # "furthest" means; one row per member per book makes it
                    # meaningless here, so it is cleared rather than carried
                    # into the subquery.
                    .order_by()
                    .values(unit_column)[:1]
                ),
                baseline_before=Subquery(
                    entries.filter(recorded_on__lte=window_start)
                    .order_by("-recorded_on", "-pk")
                    .values(unit_column)[:1]
                ),
                baseline_inside=Subquery(
                    entries.filter(recorded_on__gt=window_start)
                    .order_by("recorded_on", "pk")
                    .values(unit_column)[:1]
                ),
                entry_count=Subquery(
                    entries.order_by()
                    .values("progress")
                    .annotate(total=Count("pk"))
                    .values("total")[:1]
                ),
            )
            .order_by(F("recorded_units").desc(nulls_last=True), Lower("name"))
        )

        rows = [
            {
                "member": member,
                # None is "nothing recorded" (decision #19); a recorded zero
                # stays 0. No `or 0`: that would turn the first into the second.
                "units_read": member.recorded_units,
                "percent": (
                    None
                    if member.recorded_units is None
                    else book.percent_of(member.recorded_units)
                ),
                "has_recorded": member.recorded_units is not None,
                "movement": _movement(book, member),
            }
            for member in members
        ]

    return render(
        request,
        "club/progress.html",
        {"book": book, "rows": rows},
    )


def progress_trail(request, pk, member_pk):
    """One member's trail through one book: every number they recorded, dated.

    Public, like every other read in this app. An unknown book or member is a
    404 rather than an empty page about nobody.

    Four queries whatever the trail's length — the book, the member, the row
    and its entries — because the entries come back with their book already
    attached. `entry.units_read` and `entry.percent` both ask the book what it
    is measured in, and asking it per row would turn a link on the overview
    into a query per dot.

    Only the entries recorded in the unit the book is measured in now are on
    the trail. The rest are counted, not hidden: a book that changed measure
    already makes a member read as "not started" on the overview (decision
    #25), and this page says that out loud rather than going quietly blank.
    """
    book = get_object_or_404(Book, pk=pk)
    member = get_object_or_404(Member, pk=member_pk)

    progress = (
        Progress.objects.filter(book=book, member=member)
        .select_related("book", "member")
        .first()
    )

    rows = []
    recorded_in_other_unit = 0
    other_measure = ""

    viewer = current_member(request)
    # Only the owner, only on the current read (#31). The buttons are
    # cosmetic: `progress_entry_delete` asks the same question again.
    owner_may_remove = book.is_current and viewer is not None and viewer.pk == member.pk
    newest_pk = None

    if progress is not None:
        column = book.unit_column
        entries = list(progress.entries.select_related("progress__book"))
        # The newest entry of the whole row, whatever its unit, is the one the
        # current value agrees with (decision #26) and is never removable.
        newest_pk = entries[0].pk if entries else None
        on_this_scale = [
            entry for entry in entries if getattr(entry, column) is not None
        ]
        recorded_in_other_unit = len(entries) - len(on_this_scale)
        other_columns = {
            name
            for entry in entries
            for name in Book.READ_COLUMNS.values()
            if name != column and getattr(entry, name) is not None
        }
        other_measure = " and ".join(
            label
            for measure, label in MEASURE_LABELS.items()
            if Book.READ_COLUMNS[measure] in other_columns
        )

        for index, entry in enumerate(on_this_scale):
            # Newest first, so the entry to compare against is the next one
            # down the list. The oldest has nothing behind it and gets no
            # change figure at all — a first number is not an improvement on
            # anything.
            previous = (
                on_this_scale[index + 1]
                if index + 1 < len(on_this_scale)
                else None
            )
            change = percent_change = None

            if previous is not None:
                change = entry.units_read - previous.units_read

                if entry.percent is not None and previous.percent is not None:
                    percent_change = entry.percent - previous.percent

            rows.append(
                {
                    "entry": entry,
                    "change": change,
                    "percent_change": percent_change,
                    "may_remove": owner_may_remove and entry.pk != newest_pk,
                }
            )

    return render(
        request,
        "club/progress_trail.html",
        {
            "book": book,
            "member": member,
            "progress": progress,
            "rows": rows,
            "recorded_in_other_unit": recorded_in_other_unit,
            "other_measure": other_measure,
            "measure_label": MEASURE_LABELS[book.measure],
        },
    )


def notes(request):
    """Notes on the current book, newest first, plus the form to add one.

    Reading is open to anyone. Posting needs a name, which is attribution and
    not authorisation — decision #5.
    """
    if request.method == "POST":
        return _post_note(request)

    return _render_notes(request, NoteForm(book=Book.objects.current()))


def _chapter_filter(request):
    """The `?chapter=` value as a positive int, or None (decision #35).

    Missing, blank, junk, decimal, zero and negative all mean no filter.
    """
    raw = request.GET.get("chapter", "").strip()

    if not raw.isascii() or not raw.isdigit():
        return None

    value = int(raw)
    return value if value >= 1 else None


def _top_level_notes(book):
    """A book's top-level notes, newest first, each with its replies loaded.

    Replies are prefetched oldest first — a conversation reads downward — with
    their authors, so the query count does not grow with the thread (decision
    #19). A reply is never a top-level row, so it is never listed twice.
    """
    # `agree_count` is a Count annotation (decision #42). Aggregating drops
    # `Meta.ordering`, so the order is spelled out again (decision #23).
    return (
        book.notes.filter(parent__isnull=True)
        .select_related("author")
        .annotate(agree_count=Count("reactions"))
        .order_by("-created_on", "-pk")
        .prefetch_related(
            Prefetch(
                "replies",
                queryset=Note.objects.select_related("author").order_by(
                    "created_on", "pk"
                ),
            )
        )
    )


def _render_notes(request, form, reply_form=None):
    book = Book.objects.current()
    viewer = current_member(request)
    viewer_is_admin = is_admin(request)

    # Each note is paired with whether this viewer may remove it, asked of the
    # model rather than re-derived in the template. The button is decoration
    # either way — `note_delete` asks the same question again.
    rows = []
    chapter = _chapter_filter(request)
    top_level = _top_level_notes(book) if book else []
    if book and chapter is not None:
        top_level = top_level.filter(chapter=chapter)

    # One query for every note this viewer agrees with, never one per note.
    agreed_ids = (
        set(
            Reaction.objects.filter(member=viewer, note__book=book).values_list(
                "note_id", flat=True
            )
        )
        if viewer is not None and book is not None
        else set()
    )

    for note in top_level:
        replies = list(note.replies.all())

        # Only the form that was submitted comes back bound, so an error shows
        # under the note it belongs to and the others stay empty.
        if (
            reply_form is not None
            and reply_form.is_bound
            and reply_form.data.get("parent") == str(note.pk)
        ):
            note_reply_form = reply_form
        else:
            note_reply_form = ReplyForm(initial={"parent": note.pk})

        # One set of element ids per note, so every label points at its own box.
        note_reply_form.auto_id = f"reply_{note.pk}_%s"

        rows.append(
            {
                "note": note,
                "may_remove": note.may_be_removed_by(viewer, viewer_is_admin),
                "reply_count": len(replies),
                "agree_count": note.agree_count,
                "agreed": note.pk in agreed_ids,
                "replies": [
                    {"note": r, "may_remove": r.may_be_removed_by(viewer, viewer_is_admin)}
                    for r in replies
                ],
                "reply_form": note_reply_form,
            }
        )

    # A reply aimed at nothing valid has no note to show its error under.
    reply_target_error = (
        reply_form.errors.get("parent") if reply_form is not None else None
    )

    return render(
        request,
        "club/notes.html",
        {
            "book": book,
            "rows": rows,
            "form": form,
            "reply_target_error": reply_target_error,
            "chapter_filter": chapter,
        },
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

    # A reply names its note in a hidden `parent`; a plain note has no such key.
    if "parent" in request.POST:
        return _post_reply(request, book)

    form = NoteForm(request.POST, book=book)

    if not form.is_valid():
        return _render_notes(request, form)

    note = form.save(commit=False)
    note.book = book
    note.author = current_member(request)
    note.save()

    messages.success(request, "Note posted.")
    return redirect("club:notes")


def _post_reply(request, book):
    """Save a reply to a top-level note on the current book (decision #28)."""
    form = ReplyForm(request.POST, book=book)

    if not form.is_valid():
        return _render_notes(request, NoteForm(), form)

    reply = form.save(commit=False)
    reply.book = form.cleaned_data["parent"].book
    reply.author = current_member(request)
    reply.save()

    messages.success(request, "Reply posted.")
    return redirect("club:notes")


@require_POST
@require_member
def progress_entry_delete(request, pk, member_pk, entry_pk):
    """Remove an older entry from your own trail on the current book (#31).

    Owner only, and the admin flag does not change that. The newest entry is
    refused so the current value and the newest entry cannot disagree: fixing
    a typo is saving the right number, then removing the older wrong one.
    `Progress` itself is never touched. A refusal that is a missing step (a
    finished book, the newest entry) redirects with a message; acting on
    somebody else's trail is a 403.
    """
    book = get_object_or_404(Book, pk=pk)
    member = get_object_or_404(Member, pk=member_pk)
    entry = get_object_or_404(
        ProgressEntry, pk=entry_pk, progress__book=book, progress__member=member
    )

    if current_member(request).pk != member.pk:
        raise PermissionDenied("An entry is removed by the member whose trail it is on.")

    trail = redirect("club:progress_trail", book.pk, member.pk)

    if not book.is_current:
        messages.error(
            request, "This book is no longer being read, so its trail can't be changed."
        )
        return trail

    if entry.pk == entry.progress.entries.values_list("pk", flat=True).first():
        messages.error(
            request,
            "The newest entry can't be removed. Save the correct number first, "
            "then remove the older one.",
        )
        return trail

    entry.delete()
    messages.success(request, "Entry removed.")
    return trail


@require_POST
def note_delete(request, pk):
    """Remove a note — its author, or an admin. Decision #7.

    A 403 rather than a redirect, because a member acting on somebody else's
    note is a real refusal and not a missing step.
    """
    note = get_object_or_404(Note, pk=pk)

    if not note.may_be_removed_by(
        current_member(request), is_admin(request)
    ):
        raise PermissionDenied("A note is removed by the member who wrote it.")

    # Counted before the delete: a top-level note takes its replies with it.
    reply_count = note.replies.count()
    note.delete()

    if reply_count:
        noun = "reply" if reply_count == 1 else "replies"
        messages.success(request, f"Note removed, and {reply_count} {noun} with it.")
    else:
        messages.success(request, "Note removed.")
    return redirect("club:notes")


@require_POST
@require_member
def note_react(request, pk):
    """Toggle the viewer's "Agree" on a top-level note of the current book.

    Re-checks the target here; hiding the button is cosmetic. Anything that is
    not a top-level note on the current book writes nothing and sends the
    viewer back to the notes with a message (decisions #18, #23, #28, #42).
    `require_POST` is outermost, so a GET is a 405 whatever the session holds.
    """
    book = Book.objects.current()
    note = Note.objects.filter(pk=pk, parent__isnull=True, book=book).first()

    if book is None or note is None:
        messages.error(
            request,
            "Only a top-level note on the current book can be agreed with.",
        )
        return redirect("club:notes")

    member = current_member(request)
    deleted, _ = Reaction.objects.filter(note=note, member=member).delete()
    if not deleted:
        # A double submit that races past the filter hits the constraint;
        # get_or_create absorbs it and leaves exactly one row.
        Reaction.objects.get_or_create(note=note, member=member)

    return redirect("club:notes")


def questions(request):
    """The current book's questions and everyone's answers to them.

    Reading is open to anyone. Answering needs a name, which is attribution and
    not authorisation — decision #5.
    """
    if request.method == "POST":
        return _post_answer(request)

    return _render_questions(request)


def _answers_prefetch():
    """Answers with their members, and each answer's replies with theirs.

    One nested prefetch, so replies add exactly one query to a page however
    many exist (decision #19). Replies come oldest first from `Meta.ordering`.
    """
    return Prefetch(
        "answers",
        queryset=Answer.objects.select_related("member").prefetch_related(
            Prefetch(
                "replies", queryset=AnswerReply.objects.select_related("author")
            )
        ),
    )


def _render_questions(request, bound_form=None, reply_form=None):
    """Render the page, optionally with one form showing errors.

    Every question carries its own form, and every answer its own reply form.
    At most one of all of them is bound — the one just submitted — and the
    rest are fresh, prefilled with this viewer's existing answer where there
    is one.
    """
    book = Book.objects.current()
    viewer = current_member(request)
    viewer_is_admin = is_admin(request)

    if book is None:
        return render(request, "club/questions.html", {"book": None, "rows": []})

    open_questions = book.questions.all()
    bound_question = (
        bound_form.data.get("question") if bound_form is not None else None
    )

    rows = []
    for question in open_questions.prefetch_related(_answers_prefetch()):
        answers = list(question.answers.all())

        for answer in answers:
            if (
                reply_form is not None
                and reply_form.is_bound
                and reply_form.data.get("answer") == str(answer.pk)
            ):
                answer.reply_form = reply_form
            else:
                answer.reply_form = AnswerReplyForm(initial={"answer": answer.pk})

            # One set of element ids per answer, so every label finds its box.
            answer.reply_form.auto_id = f"answer_reply_{answer.pk}_%s"
            answer.reply_rows = [
                {
                    "reply": reply,
                    "may_remove": reply.may_be_removed_by(viewer, viewer_is_admin),
                }
                for reply in answer.replies.all()
            ]
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

    # A reply aimed at nothing valid has no answer to show its error under.
    reply_target_error = (
        reply_form.errors.get("answer") if reply_form is not None else None
    )

    return render(
        request,
        "club/questions.html",
        {"book": book, "rows": rows, "reply_target_error": reply_target_error},
    )


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

    # A reply names its answer in an `answer` key; an answer names a `question`.
    # Presence alone decides, so a blank or junk `answer` is a reply with a bad
    # target and never quietly becomes an answer (decision #43).
    if "answer" in request.POST:
        return _post_answer_reply(request, book)

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


def _post_answer_reply(request, book):
    """Save a reply to an answer on the current book (decision #43)."""
    form = AnswerReplyForm(request.POST, book=book)

    if not form.is_valid():
        return _render_questions(request, reply_form=form)

    reply = form.save(commit=False)
    reply.author = current_member(request)
    reply.save()

    messages.success(request, "Reply posted.")
    return redirect("club:questions")


@require_POST
def answer_reply_delete(request, pk):
    """Remove a reply to an answer - its author, or an admin (decision #43).

    A 403 for anyone else, unidentified included. A reply on a finished book is
    part of the read-only record (decision #23) and is refused with a message.
    """
    reply = get_object_or_404(
        AnswerReply.objects.select_related("answer__question__book"), pk=pk
    )

    if not reply.may_be_removed_by(current_member(request), is_admin(request)):
        raise PermissionDenied("A reply is removed by the member who wrote it.")

    if not reply.answer.question.book.is_current:
        messages.error(
            request,
            "This book is no longer being read, so its replies can't be removed.",
        )
        return redirect("club:questions")

    reply.delete()
    messages.success(request, "Reply removed.")
    return redirect("club:questions")


@club_admin_required
def question_add(request):
    """Post a discussion question against the current book."""
    book = Book.objects.current()

    if book is None:
        messages.error(request, "There is no current book to ask about.")
        return redirect("club:home")

    last = book.questions.aggregate(models.Max("position"))["position__max"] or 0
    form = QuestionForm(
        request.POST if request.method == "POST" else None, initial={"position": last + 1}, book=book
    )

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
    form = QuestionForm(request.POST if request.method == "POST" else None, instance=question, book=question.book)

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

    reply_count = AnswerReply.objects.filter(answer__question=question).count()

    if request.method == "POST":
        question.delete()
        if reply_count:
            noun = "reply" if reply_count == 1 else "replies"
            messages.success(
                request,
                f"Question removed, along with its answers and {reply_count} {noun}.",
            )
        else:
            messages.success(request, "Question removed, along with its answers.")
        return redirect("club:questions")

    return render(
        request,
        "club/question_confirm_delete.html",
        {"question": question, "reply_count": reply_count},
    )


HISTORY_QUERY_MAX = 200


def history(request):
    """Every book that is not the club's current read, newest finished first.

    Uncapped, and staying that way — a club reads a dozen books a year, and
    #37 holds pagination for whenever that stops being true.

    `?q=` narrows it (decision 29): every word must appear, ignoring case, in
    the title or the author. A blank `q` is no search at all.

    `?year=` narrows it to the calendar year of `finished_on` (decision 44),
    ANDed with `q`. Only a year the page offers filters; anything else is
    ignored, so no raw input ever reaches `int()`.
    """
    query = request.GET.get("q", "").strip()[:HISTORY_QUERY_MAX]
    # One query, derived from the data and deliberately not narrowed by `q` or
    # the chosen year, so the choices stay put under the member's hands.
    years = [
        d.year
        for d in Book.objects.filter(
            is_current=False, finished_on__isnull=False
        ).dates("finished_on", "year", order="DESC")
    ]
    raw_year = request.GET.get("year", "")
    year = next((y for y in years if str(y) == raw_year), None)
    books = (
        Book.objects.filter(is_current=False)
        .annotate(
            # Annotated rather than asked per row: the archive is uncapped, so
            # a property that averaged in Python would be one query per entry.
            member_rating_average=Avg("ratings__score"),
            member_rating_count=Count("ratings"),
        )
        # Spelled out rather than inherited. Aggregating drops `Meta.ordering`,
        # which turned the archive back into primary key order the moment the
        # averages were added — silently, because both orders look plausible
        # until the dates disagree.
        .order_by(
            F("finished_on").desc(nulls_last=True),
            F("started_on").desc(nulls_last=True),
            "-pk",
        )
    )
    # The filter reads only the book's own columns, so it adds no join and the
    # rating aggregates above are not inflated. `icontains` escapes `%` and `_`.
    for word in query.split():
        books = books.filter(Q(title__icontains=word) | Q(author__icontains=word))
    if year is not None:
        books = books.filter(finished_on__year=year)

    books = list(books)

    return render(
        request,
        "club/history.html",
        {
            "books": books,
            "query": query,
            "years": years,
            "year": year,
            "match_count": len(books) if query or year is not None else None,
            "archive_has_books": bool(books)
            or Book.objects.filter(is_current=False).exists(),
        },
    )


def history_detail(request, pk):
    """One book's discussion, replayed read-only — except the rating.

    This works because notes, questions and answers carried a book foreign key
    from the start (decision #8) rather than being scoped to whatever happened
    to be current. Nothing about the discussion writes, and nothing about it is
    offered to write.

    The rating is the exception decision #23 carves out: you rate a book once
    you have finished it, and this page is the only place a finished book
    lives. The form posts to `book_rate`, which re-checks everything this view
    decided before showing it.
    """
    book = get_object_or_404(Book, pk=pk)
    viewer = current_member(request)
    ratings = list(book.ratings.select_related("member"))
    scores = [rating.score for rating in ratings]
    my_rating = next(
        (r for r in ratings if viewer is not None and r.member_id == viewer.pk),
        None,
    )

    return render(
        request,
        "club/history_detail.html",
        {
            "book": book,
            "notes": _top_level_notes(book),
            "questions": book.questions.prefetch_related(_answers_prefetch()),
            # The book comes along because every row prints its count in the
            # book's own unit and asks the book for its percentage; without it
            # that is a query per member.
            "progress": book.progress.select_related("member", "book"),
            "ratings": ratings,
            # Averaged here rather than in the database, because the rows are
            # already loaded to be listed underneath it.
            "rating_average": sum(scores) / len(scores) if scores else None,
            "my_rating": my_rating,
            # Unbound and prefilled from the row this member already has, so
            # the control shows their standing score rather than asking again
            # from blank. Absent entirely when there is nobody to attribute a
            # score to, or nothing finished to score.
            "rating_form": (
                MemberRatingForm(initial=_rating_initial(my_rating))
                if viewer is not None and book.is_finished
                else None
            ),
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
        request.POST if request.method == "POST" else None, initial={"started_on": timezone.localdate()}
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
        request.POST if request.method == "POST" else None,
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
def book_reopen(request, pk):
    """Make a finished book the current read again - the inverse of finish.

    Only the flag and `finished_on` move. The rating, per-member scores and the
    whole discussion stay on the row, so re-finishing picks up where it left
    off. Refused while another book is current: the partial unique index allows
    one, and the admin decides which book to set aside (decision #30).
    """
    book = get_object_or_404(Book, pk=pk, is_current=False)
    other = Book.objects.current()

    if request.method == "POST":
        if other is not None:
            messages.error(
                request,
                f"{other.title} is the current read. Finish it before "
                f"reopening {book.title}.",
            )
            return redirect("club:book_reopen", pk=book.pk)

        try:
            with transaction.atomic():
                book.is_current = True
                book.finished_on = None
                book.save(update_fields=["is_current", "finished_on"])
        except IntegrityError:
            messages.error(
                request,
                f"Another book became the current read. Nothing changed "
                f"for {book.title}.",
            )
            return redirect("club:book_reopen", pk=book.pk)

        messages.success(request, f"{book.title} is the current read again.")
        return redirect("club:home")

    return render(request, "club/book_reopen.html", {"book": book, "other": other})


@club_admin_required
def book_edit(request, pk):
    """Correct a book's metadata, current or archived.

    Not the current-read flag: that moves through starting and finishing, which
    is where the rule about there being one of them lives.
    """
    book = get_object_or_404(Book, pk=pk)
    form = BookEditForm(request.POST if request.method == "POST" else None, instance=book)

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


def _rating_initial(rating):
    """Prefill data for `MemberRatingForm` from an existing row, or nothing.

    One helper because two views prefill the same form: the archive page, which
    renders it inline, and `book_rate`, which renders it again when a submission
    comes back with an error or somebody arrives at the URL directly.
    """
    return {"score": rating.score} if rating is not None else None


BOOK_DELETE_LINES = (
    ("progress", "progress record", "progress records"),
    ("entries", "progress entry", "progress entries"),
    ("notes", "note", "notes"),
    ("note_replies", "reply to a note", "replies to notes"),
    ("reactions", "reaction", "reactions"),
    ("questions", "question", "questions"),
    ("answers", "answer", "answers"),
    ("answer_replies", "reply to an answer", "replies to answers"),
    ("ratings", "member score", "member scores"),
)


def _book_attachments(book):
    """Count what deleting `book` takes with it: a fixed nine queries.

    Returns the raw counts and the non-zero ones as ready-made phrases, so the
    confirmation page and the success message cannot disagree.
    """
    notes = Note.objects.filter(book=book)
    counts = {
        "progress": Progress.objects.filter(book=book).count(),
        "entries": ProgressEntry.objects.filter(progress__book=book).count(),
        "notes": notes.filter(parent__isnull=True).count(),
        "note_replies": notes.filter(parent__isnull=False).count(),
        "reactions": Reaction.objects.filter(note__book=book).count(),
        "questions": Question.objects.filter(book=book).count(),
        "answers": Answer.objects.filter(question__book=book).count(),
        "answer_replies": AnswerReply.objects.filter(
            answer__question__book=book
        ).count(),
        "ratings": MemberRating.objects.filter(book=book).count(),
    }
    phrases = [
        f"{counts[key]} {one if counts[key] == 1 else many}"
        for key, one, many in BOOK_DELETE_LINES
        if counts[key]
    ]
    return counts, phrases


@require_http_methods(["GET", "POST"])
@club_admin_required
def book_delete(request, pk):
    """Remove a book created by mistake, and everything attached to it.

    GET renders a confirmation that counts what goes with the book and changes
    nothing; POST deletes in one transaction (decision #45). Every FK off a
    book cascades, and the PROTECT FKs point at Member, so nothing blocks it.
    """
    book = get_object_or_404(Book, pk=pk)
    counts, phrases = _book_attachments(book)

    if request.method == "POST":
        was_current = book.is_current
        title = book.title
        with transaction.atomic():
            book.delete()
        if phrases:
            messages.success(
                request, f"{title} deleted, along with {', '.join(phrases)}."
            )
        else:
            messages.success(request, f"{title} deleted.")
        return redirect("club:home" if was_current else "club:history")

    return render(
        request,
        "club/book_confirm_delete.html",
        {"book": book, "counts": counts, "phrases": phrases},
    )


@require_member
def book_rate(request, pk):
    """Record this member's score for a book the club has finished.

    The archive is read-only for discussion and not for this (decision #23):
    you rate a book once you have read it, and the history page is the only
    place a finished book lives. That page posts here; this view is also the
    GET-and-error surface, so a failed submission comes back somewhere with a
    form on it rather than losing the score on a redirect.

    A book is finished when it is not current and has a finish date
    (`Book.is_finished`, decision #36). The current read is refused — a score
    for a book somebody is halfway through is not a score — and so is a book
    with no finish date, which the club never finished. Refused here and not
    only hidden there: a hidden control is decoration.
    """
    book = get_object_or_404(Book, pk=pk)

    if book.is_current:
        messages.error(
            request,
            f"The club is still reading {book.title}. Rate it once it is finished.",
        )
        return redirect("club:history_detail", pk=book.pk)

    if not book.is_finished:
        messages.error(
            request,
            f"{book.title} has no finish date yet, so it cannot be rated. "
            "Ratings open once it has one.",
        )
        return redirect("club:history_detail", pk=book.pk)

    member = current_member(request)
    mine = MemberRating.objects.filter(book=book, member=member).first()
    form = MemberRatingForm(request.POST if request.method == "POST" else None, initial=_rating_initial(mine))

    if request.method == "POST" and form.is_valid():
        MemberRating.objects.update_or_create(
            book=book,
            member=member,
            defaults={"score": form.cleaned_data["score"]},
        )
        messages.success(request, f"Your rating for {book.title} is saved.")
        return redirect("club:history_detail", pk=book.pk)

    return render(
        request,
        "club/book_rate.html",
        {"form": form, "book": book, "my_rating": mine},
    )
