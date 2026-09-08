# Decisions

Calls made while turning `_docs/plan.md` into a backlog. The plan is a scope
document and left a dozen questions open; they are settled here so that issues
stop re-litigating them.

Where an issue and this file disagree, this file wins — raise it on the issue
rather than quietly doing it another way.

## 1. Progress is stored as pages read; the percentage is derived

`Progress` holds `pages_read` against the member and the book. `Book` holds
`total_pages`. The percentage shown anywhere is computed, never stored.

Why: the plan says "percent complete **or** pages/chapters read", and that "or"
hides a fork. Comparing members — the entire point of the progress feature — needs
a common scale. One canonical number derived from the book means two members can
never disagree about what 50% of the same book is.

Cost accepted: a book with no page count recorded cannot show percentages, only
raw pages. That is a data-entry problem, not a modelling one.

## 2. One `Book` model with a current-read flag

There is no separate "current book" and "past book" model. A book is a row with
a flag, and finishing it clears the flag.

Why: the archive has to show a finished book's notes, answers and final progress,
all of which point at the book by foreign key. Moving a row between tables at
finish time would mean rewriting every one of those references, on the one
operation that must not lose anything.

At most one book may carry the flag, enforced in the database rather than by
convention. **No current book is a legitimate state** — the club sits between
reads, and every page that shows the current book has an empty state for it.

## 3. Members are deactivated, never deleted

`Member.is_active` comes off the roster and the progress table when false. The
row itself stays forever.

Why: a member's notes and answers are attributed to them by foreign key. Deleting
the row either cascades and destroys club history, or orphans it and leaves
anonymous text. Neither is acceptable for an archive whose entire purpose is
remembering. A member who leaves the club leaves the roster, not the record.

## 4. Identity is chosen once per session, not per form

A viewer picks their name from the roster once; the choice lives in the session
and reaches every template as `current_member`. No individual form asks who you
are.

Why: a name dropdown repeated on the progress form, the note form and the answer
form is three chances to post as the wrong person, and it makes every one of
those forms carry a field it should not have. It also means a view can attribute
a post without trusting anything the client submitted.

## 5. The PIN is not security, and nothing should pretend otherwise

The admin PIN is a shared string in settings, compared with `hmac.compare_digest`
and remembered as a session flag. It stops a member from wandering into the
history editor by accident. It stops nothing else.

Why: the plan explicitly rejected real authentication. Anyone who can open the
site can pick anyone's name, and anyone who learns the PIN is an admin forever.
Writing this down matters because the alternative is someone later mistaking the
PIN for a permission system and building something load-bearing on top of it.

What follows from it: never store anything in this app that would be damaging to
leak, and always re-check the flag in the view — a hidden button is decoration.

## 6. One answer per member per question, edited in place

`Answer` is unique on (question, member). Resubmitting updates the existing row.

Why: an answer is a standing position, not a remark. Ten rows from one member on
one question is noise, and a uniqueness constraint without an update path is an
integrity error waiting for the first person who changes their mind.

## 7. Notes are immutable; answers are editable

A note can be deleted by its author or an admin, but never edited. An answer can
be edited by its author.

Why: a note is a timestamped reaction — "I did not see that coming" — and editing
it after the fact rewrites the conversation around it. An answer is a position on
a fixed question, and refining it is the point. Deletion stays available for
notes because the alternative to deleting a regretted note is not posting one.

Note that "its author" here is a convention, not a boundary — see #5.

## 8. Everything hangs off a book

Notes, questions, answers and progress all carry a `Book` foreign key. Nothing is
scoped to "the current book" implicitly.

Why: the archive shows a past book's discussion, which requires that the
discussion was tied to that book and not to whatever happened to be current. New
posts are restricted to the current book by the views, not by the schema.

## 9. Ratings are club-level, recorded at finish time

One optional rating per book, captured by the admin on the finish form.

Why: the plan says "optionally retained notes/rating" without saying whose. A
per-member rating is a nicer feature and a bigger model — a whole extra table and
an aggregate on every history row. If the club wants it, it is a v2 issue.

## 10. `Member.role` is a label with no behaviour

Free text: "Founder", "Host", "Snack coordinator". It confers nothing.

Why: the plan lists roles alongside a PIN-based admin gate, which means roles are
descriptive. Wiring permissions to a text field would produce a role system
nobody asked for, in an app that has already decided it has no authentication.

## 11. `src/reading_club_manager/` stays

The stub package from the original uv skeleton is dead code, and it is staying.

Why: `pyproject.toml` declares the `uv_build` backend and a `[project.scripts]`
entry pointing into that package. Deleting the directory alone breaks `uv sync`.
Removing it properly means editing the build configuration mid-project to delete
something that costs nothing — a real chance of breaking the environment for no
functional gain.

## 12. Django's test runner, not pytest

Tests run with `manage.py test`. `pytest` is not installed and will not be
added for v1.

Why, in the order that decided it:

**The assertions this app needs are `TestCase` methods.** The remaining issues
lean on `assertRedirects` (every POST-then-redirect), `assertContains` (every
smoke test), `assertFormError` (duplicate member names, empty note bodies) and
`assertNumQueries` (the progress overview's N+1 risk). Under pytest you either
keep writing `TestCase` classes and gain nothing, or you trade those helpers for
fixtures and lose more than you win.

**Pytest's headline advantage does not apply at this size.** Assertion
introspection pays off on complex comparisons; this suite mostly asserts a
status code and the presence of a string. `parametrize` would genuinely help
with the percentage boundaries in #9 — the one real loss — and `subTest` covers
that case adequately.

**Cost is two dependencies, a settings shim, and a second idiom.** In a project
whose point is learning Django, every doc page and answer you will hit uses
`TestCase` and `manage.py test`. Running a second testing model alongside that
is cost without a matching benefit.

Not urgent to revisit, which is itself part of the argument: `pytest-django`
runs existing Django `TestCase` classes unchanged, so adopting it later means
adding two dependencies and a config block, not rewriting tests. There is no
deadline here and no reason to spend the dependencies in advance of the need.

Revisit if CI arrives and its reporting is wanted, or if the suite passes
roughly 50 tests and setup duplication starts to hurt.

## 13. `Member.joined_on` is editable, and names are unique case-insensitively

Settled while building the `Member` model (#3). Two calls, both about the roster
row:

**`joined_on` defaults to today but stays editable.** The field is
`DateField(default=timezone.localdate)` — a callable, no parentheses — and not
`auto_now_add=True`.

Why: `auto_now_add` makes the field non-editable, which hides it from every form
including the admin's and leaves a wrong date uncorrectable. The club has
founding members who joined long before this app existed, and the person typing
them in is the one who knows when. `localdate` rather than `date.today` because
`USE_TZ` is on and `TIME_ZONE` is `Europe/Madrid`, so "today" is the club's
today, not UTC's.

**Names are unique case-insensitively**, enforced by
`UniqueConstraint(Lower("name"), name="member_name_unique_ci")` in `Meta`
alongside plain `unique=True`.

Why: a viewer identifies themselves by picking a name off this roster
(decision #4), and "Ada" beside "ada" makes that pick a coin toss. `unique=True`
alone does not get this — SQLite's default collation is case-sensitive and
happily stores both rows. Keeping both rules means Django's model validation
gives an exact duplicate a field-level error and a case-only duplicate a
form-level one, so the roster form in #5 shows a form error rather than a 500.

Cost accepted: case folding is all the normalisation there is. "José" and "Jose"
are two members, and so are names differing by an internal double space. Django's
form fields already strip surrounding whitespace, which covers the common typo.

## 14. What the admin PIN gate does when it refuses

Settled while building the PIN gate (#4). Four calls, all about the gate rather
than the PIN itself — decision #5 already settled that the PIN is not security.

**A blank PIN fails closed.** `CLUB_ADMIN_PIN` is
`os.environ.get("CLUB_ADMIN_PIN", "0000").strip()`. When it resolves to `""` the
PIN page says admin mode is unavailable, the comparison is never reached, and no
submitted value — the empty string included — sets the flag.

Why: `CLUB_ADMIN_PIN=` in the environment yields `""`, not the `0000` default,
so a deployment that meant to unset the PIN would otherwise hand admin mode to
anyone who submitted an empty field. Unreachable is the safe reading of "no PIN
configured"; open to everyone is not.

**Refusal splits on method: 302 on GET or HEAD, 403 on everything else.** The
`club_admin_required` decorator redirects a safe method to `/admin-pin/` with
`?next=` back to where it came from, and raises `PermissionDenied` for anything
else.

Why: a redirect answers a POST with a GET and silently drops the payload. The
typed data is lost either way, but a 403 says a refusal happened, where an
automated POST would read a 302 as success. On a GET the redirect is genuinely
the missing step, so it is the more useful answer there.

**A submitted `next` is validated before it is followed.**
`url_has_allowed_host_and_scheme` against `request.get_host()`, plus a rejection
of `/admin-pin/` and `/admin-pin/exit/` as destinations, falling back to
`club:home`.

Why: `next` is client data reaching a `Location` header. The host check keeps a
hand-edited link from bouncing a member off-site after they type the PIN; the
self-reference check keeps a bookmarked `?next=/admin-pin/` from looping the PIN
page onto itself or walking straight back out through the exit route.

**Admin mode lasts exactly as long as the session cookie.** No session settings
are changed: Django's default two weeks, surviving a browser restart, not
sliding on activity. It ends deliberately at `/admin-pin/exit/`.

Why: `SESSION_EXPIRE_AT_BROWSER_CLOSE` is not available, because `member_id`
(#6) shares the same cookie and wants the longer life. An expiry belonging to
admin mode alone is #24, deliberately deferred — decision #5 says hardening a
shared PIN invites the mistake of trusting it.

Consequence accepted: logging out of Django's own `/admin/` also drops admin
mode, because `django.contrib.auth.logout()` flushes the whole session. There is
a test named after it so the next person meets it in a test report rather than
in the browser.

## 15. The roster form carries `joined_on`, and never `is_active`

Settled while building the roster page (#5). Two small calls about which fields
`MemberForm` exposes.

**`joined_on` is on the form.** The issue names name and role; the form has all
three.

Why: the goal of #5 is a roster the club maintains without anyone holding a
Django superuser account, and decision #13 kept `joined_on` editable precisely
because founding members joined long before this app existed. A form without it
would leave the club's own page unable to record a date the Django admin can,
which is the gap this issue exists to close.

**`is_active` is not on the form.** Deactivating is a POST to
`club:member_toggle` and nothing else.

Why: it is a different act from renaming someone, and a checkbox tucked beside
the name field is how a member gets dropped off the roster by an admin who meant
to fix a typo. A separate button with its own confirmation-shaped wording keeps
the two apart. There is still no delete, ever — decision #3.

## 16. Both gates refuse the same way, and identity lives in `club/identity.py`

Settled while building viewer identity (#6). Decision #14 fixed how the admin
gate refuses; this extends the same rule to the identity gate and says where the
lookup lives.

**`require_member` refuses exactly as `club_admin_required` does**: 302 to the
picker with `?next=` on a GET or HEAD, 403 on anything else. Both decorators
call one `_refuse` helper, so there is one refusal rule in the app rather than
two that drift.

Why: the argument from #14 holds unchanged — a redirect answers a POST with a
GET and drops the payload. It is stronger here, because the routes behind this
gate include POST-only ones (`/progress/update/`). Sending `?next=/progress/
update/` through the picker would land the viewer back on that URL as a GET,
which is a 405: the redirect is not merely lossy there, it is broken.

**A session naming a member who is gone clears itself.** `current_member`
resolves through `Member.objects.filter(pk=..., is_active=True)` and, on a miss,
pops the session key and returns `None`.

Why: sessions last two weeks and rosters change inside that, so a viewer who was
deactivated mid-session is ordinary rather than exotic. Their next page load
should show them as unidentified, one click from the picker — not a 500 on every
page including the one that would let them fix it.

**The lookup lives in `club/identity.py`**, imported by the context processor,
the decorator and the views, and cached on the request.

Why: three callers on the same request, and the alternative is the decorator
importing from `context_processors.py`, which reads backwards. Caching keeps it
to one query per request rather than one per caller.

**The two session keys are unrelated.** `member_id` says who you are;
`is_club_admin` says the PIN has been typed. Neither implies the other, and
leaving one alone does not touch the other.

Why: decision #5. Picking a name is not a claim to be trusted, and the PIN is
not a claim about who you are. Tying them together would be the first step
towards mistaking either one for a permission system.

## 17. Book ordering states its null placement, and the rating range is a constraint

Settled while building the `Book` model (#7). Two details the issue left open.

**`Book.Meta.ordering` is newest-finished first, with nulls explicitly last:**
`F("finished_on").desc(nulls_last=True)`, then the same on `started_on`, then
`-pk`.

Why: the archive (#14) wants newest-finished first, and both dates are nullable
— an unfinished book has neither. Left to the database, null placement under
`DESC` is a per-backend detail, and the one row that is always unfinished is the
current read, which must not lead a list of finished books. `-pk` is the final
tiebreak so the order is total: two books finished the same day still come back
in a stable order rather than whatever the query planner returns.

**The 1-to-5 rating is a `CheckConstraint` as well as field validators.**

Why: validators run in forms, which is where a typo actually arrives, and the
constraint runs everywhere else — a fixture, the shell, a future management
command. Decision #2 already puts the at-most-one-current rule in the database
for the same reason: a rule enforced only in the code that remembered it is not
enforced. Both carry a `violation_error_message`, so `full_clean` and the admin
show a sentence rather than a constraint name.

**No `save()` override guards either rule.** Moving the current-read flag from
one book to the next is two saves in one transaction, and #14's finish flow does
it explicitly.

Why: a `save()` that silently cleared the other book's flag would make finishing
a book a side effect of starting the next one, and would hide the moment the
club has no current read — which decision #2 says is a state the app supports,
not a gap to paper over.

## 18. `/progress/update/` answers GET, and the derived percentage is capped

Settled while building progress (#9). Two calls the issue left open.

**The route takes GET as well as POST**, and `_docs/api.md` has been corrected
from the POST-only row it carried while the route was still planned.

Why: #9 requires that an unidentified visitor is sent to the picker and returned
afterwards, and a return needs somewhere to land. Decision #16 makes an
unidentified POST a 403 precisely because `?next=` to a POST-only route lands on
a 405 — so a POST-only progress route could not satisfy that requirement at all.
GET renders the form; POST saves and redirects, so a refresh cannot resubmit.

The GET writes nothing. `Progress.objects.filter(...).first()` and an unsaved
instance, not `get_or_create`: a member who opens the form and closes it again
has recorded nothing, and the overview shows them as zero either way.

**`Progress.percent` is capped at 100** and returns `None` when the book has no
page count — or a page count of zero, which is a typo rather than a book.

Why the cap: pages read can legitimately exceed the total after an admin
corrects a page count downwards, and the number feeds a CSS bar whose width is
that percentage. A bar past its own track is a rendering bug, not information.
The stored pages stay untouched, so nothing is lost — only the display is
clamped.

**Recording progress when no book is current redirects home with an error
message** rather than returning a status code.

Why: this is not a refusal about who the viewer is, which is what a 403 says.
It is an action that has momentarily stopped meaning anything, and the club
member wants to be told so on a page they can read. Nothing is written either
way, and the test asserts that.

## 19. Nothing recorded and a recorded zero are different, and the arithmetic lives on `Book`

Settled while building the progress overview (#10).

**`Book.percent_of(pages_read)` owns the calculation**, and `Progress.percent`
calls it.

Why: two callers read the same book. A stored `Progress` row has one, and the
overview annotates each member with a page count through a subquery and has no
`Progress` instance to ask. Decision #1 exists so that two members can never
disagree about what half of the same book is; two copies of the arithmetic would
be exactly the disagreement it was written to prevent.

**A member with no `Progress` row is annotated `None`, not zero**, and the table
says "not started" for them and "0 of 880" for somebody who recorded a zero.

Why: they sort the same and neither is omitted — #10 is explicit that the person
who has not started is who the table is about. But they mean different things.
"Not started" is a fact about the club; a recorded zero is a member saying "I
have the book and I am on page nought", which is a different sentence. Design
system: never a bare zero.

**One query for the roster, whatever its size**, via `Subquery` rather than
walking `member.progress` per row, and `assertNumQueries(2)` pins it at two
members and again at twenty-two.

Why: the N+1 here is invisible at the size the club will ever be, which is
exactly why it needs a test rather than a look. The count is asserted twice at
different sizes so the test says "does not grow", not "was two once".

**Progress is a table, not a chart.** The bar is a CSS width carrying
`aria-hidden="true"`, with the percentage as text beside it.

Why: the design system gives the bar the whole visual budget and says the number
always sits next to it. The bar repeats what the text already says, so announcing
it twice to a screen reader is noise; hiding it leaves the number, which is the
part that carries the meaning.

## 20. A note's author is `PROTECT`, and the nav names Notes and Questions separately

Settled while building notes (#11).

**`Note.author` is `on_delete=PROTECT`.** Deleting a member who has written
anything raises rather than cascading or orphaning.

Why: decision #3 says a member who leaves the club leaves the roster, not the
record, and `MemberAdmin` already refuses deletion. That refusal lives in one
admin class, which a fixture, a shell or a future management command walks
straight past. `PROTECT` is the same rule in the schema, where everything has to
meet it. `Progress` stays `CASCADE` on both sides: a page count is not a
contribution to the record, and keeping one for a member who is gone tells the
club nothing.

`Note.book` is `CASCADE` in the other direction — a book's discussion is about
that book and means nothing without it.

**Who may remove a note is a model method, `Note.may_be_removed_by`**, and the
template asks it through the view rather than re-deriving the rule.

Why: the button and the POST handler must not be able to disagree. AGENTS.md
already says hiding a control is decoration; this keeps the decoration honest by
having it read from the same place the enforcement does.

**The nav says "Notes" and, from #12, "Questions" — not one "Discussion" entry.**

Why: #2 sketched a single Discussion link, before the two surfaces existed. They
are different acts — a note is a reaction anyone posts, a question is a prompt
only an admin posts — they live at different URLs, and a member looking for one
should not have to guess which page a "Discussion" link lands on.

## 21. One answer form per question, and the question id is a form field

Settled while building answers (#13).

**Every question on `/questions/` carries its own form, all posting to
`/questions/`**, and the question is a hidden `ModelChoiceField` whose queryset
is the current book's questions.

Why: the alternative is a route per question, which is a URL for something that
is not a resource. Making the question a form field rather than a hand-parsed
`request.POST["question"]` means a deleted question, a question on a finished
book, a missing id and a hand-typed `?question=abc` all arrive as the same form
error instead of four code paths, one of which would have been a 500 on
`int("abc")`. Answering a finished book's question is refused by that queryset
and nothing else — which is the check #14 will reuse.

On a failed submission only the offending question's form comes back bound. The
rest are rebuilt fresh, so one mistake does not blank what the member typed
under every other question.

**`update_or_create`, not a `ModelForm` bound to an instance.** The form is a
plain `Form` and the view writes through the manager.

Why: decision #6 wants one row per member per question, edited in place. Asking
for the existing row first and binding a `ModelForm` to it would work and would
also be a lookup, a branch and a `save()` where `update_or_create` is one call
that says what it does.

**An answer shows "edited" only when the timestamps differ by more than a
second.** `auto_now_add` and `auto_now` both fire on the first save, and they
are not identical to the microsecond.

Why: without the tolerance every answer would claim to have been edited the
moment it was written, which is worse than not saying at all.

## 22. The archive lists everything that is not current, and `history_detail` accepts the current book

Settled while building the archive (#14).

**`/history/` filters on `is_current=False`, not on `finished_on__isnull=False`.**

Why: the two differ only for a book with no finish date recorded — entered
through the admin, or started and set aside. Filtering on the finish date would
make that book invisible everywhere: not on the landing page, not in the
archive, findable only through `/admin/`. Listing it with "no finish date
recorded" is the empty state the design system asks for, and it is also the
prompt that gets the date filled in. `Book.Meta.ordering` already places those
rows last (decision #17).

**`/history/<pk>/` renders the current book too**, marked as still open with
links to the live notes and questions, rather than 404ing.

Why: it is the same read-only replay of the same rows, and the flag is the only
difference. A 404 would mean a link to a book's discussion breaks the moment
somebody starts reading it again, which #21 is going to make possible.

**Finishing is a form on the book, not a button.** `book_finish` takes a date
defaulting to today and an optional rating, and `finished_on` is required there
although the model allows null.

Why: null is right on the model — a book being read has no finish date — and
wrong at this moment, which is precisely the moment it acquires one. The rating
stays optional: decision #9 makes it one club-level number, and a club that
cannot agree on one should not be blocked from closing the book.

**`book_start` pre-checks for a current read and also catches `IntegrityError`.**

Why: the pre-check gives the readable sentence #14 asks for. It is not a lock,
though, and the constraint from decision #2 is real, so the far-fetched case of
two admins starting a book at once still has to be a form error rather than a
debug page.

**Deleting a note stays possible on a finished book.** The archive page offers
no such button, but `note_delete` does not check whether the book is closed.

Why: decision #7 gives an author the ability to remove a regretted note, and
that is the whole reason posting one feels safe. Making it expire when the club
moves on would take it away exactly when the note becomes permanent. Posting is
what the archive refuses; removing your own words is not posting.
