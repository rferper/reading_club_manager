import hmac
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .decorators import club_admin_required
from .forms import AdminPinForm, MemberForm
from .models import Member


def home(request):
    """Placeholder landing page.

    Issue #8 replaces this with the current book and its details.
    """
    return render(request, "club/home.html")


def _safe_next(request, next_url):
    """The submitted `next`, or None when it cannot be trusted.

    Rejects anything pointing off this host or scheme, and the PIN pages
    themselves, so a bookmarked or hand-edited `?next=` cannot bounce the PIN
    page back to itself.
    """
    if not next_url:
        return None

    if not url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return None

    if urlsplit(next_url).path in {
        reverse("club:admin_pin"),
        reverse("club:admin_exit"),
    }:
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
