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

That issue was #16, and this decision survived it. `MemberRating` sits **beside**
`Book.rating`, not instead of it: what the club agreed on out loud when it closed
the book is a different fact from the mean of five private opinions, and neither
is derived from the other. See #23.

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

## 23. The archive is closed to the discussion and open to the rating

Settled while building per-member ratings (#16). This narrows decision #22's
read-only rule for `/history/<pk>/`; it does not overturn it.

**A finished book takes no new note, answer or progress, and does take a
rating.** The page used to say "Read-only. Nothing here can be added to or
changed." It now names the discussion as the thing that is closed and says
ratings stay open.

Why: the old sentence was true while everything on that page was something the
club said *while* it was reading. A score is the opposite kind of fact — you
cannot honestly give one until you have finished, and a finished book lives
nowhere else in the app. Read literally, the old rule forbade the one act the
archive exists to make possible.

**The form is on `/history/<pk>/` itself; `/books/<pk>/rate/` is where it
posts** — and also the page that renders it for a direct GET or a rejected
score.

Why: one number and a button do not need a page of their own, and a member who
has to click through to change a 4 into a 5 will not bother. The route still
exists because a POST needs a destination and, by the POST-then-redirect rule in
`_docs/api.md`, a redirect cannot carry a bound form: a rejected score needs
somewhere to come back to with its error still attached. So the archive page
only ever renders the form unbound, and `book_rate` owns every other state of
it. Both prefill from the same helper, so the two cannot disagree about what the
member's standing score is.

**Rating the current read is refused in the view, not merely hidden in the
template**, and refused with a message and a redirect rather than a status code.

Why: AGENTS.md — hiding a control is decoration, and this is the check that
makes the hiding honest. A message rather than a 403 for the reason decision #18
gives about recording progress with no current book: a 403 says the viewer is
the wrong person, and that is not what happened. The action has momentarily
stopped meaning anything, and the member should be told so on a page they can
read.

**The average is annotated on `/history/` and computed in Python on
`/history/<pk>/`.** Different answers on the two pages, deliberately.

Why: the archive is uncapped (decision #22), so asking each book for its own
average would be a query per entry — `Avg` and `Count` annotations keep it at
one, pinned by `assertNumQueries` the way decision #19 pins the progress
overview. Aggregating also drops `Book.Meta.ordering`, so `history` now spells
decision #17's ordering out explicitly; left alone it silently reverted to
primary-key order, which looks plausible right up until two finish dates
disagree. The detail page has already loaded every row to print the names beside
the scores, so averaging them again in the database would be a second query for
arithmetic on data already in hand.

**`dev_seed.json` carries four scores on the finished book, one of them from the
deactivated member, and leaves one member unrated.** They average 4.3 against a
club rating of 5.

Why: the fixture's job (#15) is to put the awkward states in front of a
newcomer without anybody typing them. A seed where every member had rated, and
where the average landed on the club's own number, would show the feature and
hide the reason it is a second column rather than the same one — decision #9's
point that what the club agreed out loud and what five people privately thought
are different facts.

## 24. Chapters are the second denominator, and a book has only one

Settled while building chapter progress (#17). The issue was filed with two
options and this is the one it closes on.

**A book with no page count declares a chapter count; a member never types a
percentage.**

Why: decision #1 exists so that two members can never disagree about what half
of the same book is. A typed percentage is that disagreement made storable —
Ada's 50% and Ben's 50% would be two opinions about the same book with nothing
to reconcile them, and comparing members is the entire point of the feature. It
would also break the one rule the model has held since #7: no percentage is
ever stored. A chapter count keeps both. The book owns the denominator, the
member records a count, `Book.percent_of()` stays the only place the arithmetic
lives (decision #19), and nothing about how a percentage is produced changes —
only what it is divided by.

It is also the smaller change. A typed percentage means a second, differently
shaped path through progress: a nullable percent column, a branch in the form,
a branch in the overview, and a permanent question about what happens when a
book that had typed percentages later gains a page count.

**A book carries at most one denominator, and a `CheckConstraint` says so.**
Both counts at once is refused in the database, with a
`violation_error_message`, and again by a form error that names which one to
keep.

Why: two denominators is two answers to "how far is Ada", which is the thing
decision #1 was written to prevent. In the database for the reason decisions #2
and #17 already give: a rule enforced only in the form that remembered it is
not enforced, and a fixture, a shell or a future management command all walk
straight past a form. The form error exists because a constraint message cannot
say which of the two the club should keep, and that is the only question the
admin actually has.

**`Book.measure` and `Book.total_units` are where the choice is read**, and
`total_pages` and `pages_read` keep their names.

Why: renaming them to something unit-neutral is roughly 140 references across
17 files, and the names are honest — `pages_read` holds pages, always. The
generic reading belongs on the two derived properties, which is also the only
place the branch has to exist. Pages stay the default measure, so a book with
neither count behaves exactly as it did before this issue: raw pages, no
percentage, no upper bound.

**A count of zero is a typo rather than a measure.** `total_chapters = 0` reads
as no chapter count at all, the same answer `percent_of` has always given a page
count of zero, and `Progress.Meta.ordering` asks `> 0` rather than `IS NOT NULL`
so that the two cannot disagree.

## 25. `chapters_read` is a second column, and it is nullable

Settled while building chapter progress (#17), and the reason a book may change
measure without anybody losing anything.

**Chapters are recorded in `Progress.chapters_read`, never in `pages_read`.**

Why: a member who recorded 431 pages before the book dropped its page count must
not silently become 431 chapters in. That is not a display problem — it is a
number that was true about one scale being read against another, which is
silent data corruption. Two columns cost one migration and keep every recorded
number meaning what it meant when it was typed. The migration is additive and
rewrites no existing row.

**The column is nullable where `pages_read` defaults to zero**, and that
difference is decision #19 applied to a case it did not anticipate.

Why: on a book that has always been measured in pages, the existence of the row
is what says somebody recorded something. On a book that changed measure, the
row is already there and says nothing at all about chapters — so a defaulted
zero would put the member on the table at "0 of 30", which is a sentence they
never said. Null means nothing recorded in chapters, zero means "I have the book
and I am on chapter nought", and the overview shows the first as **not started**
and the second as a recorded zero, exactly as decision #19 asks. `pages_read`
is left alone rather than made nullable to match: every row that exists has a
real page count in it, and a friendlier conversion after a measure change is
#21.

**`ProgressForm` drops the field the book does not measure in** rather than
hiding it, so a hand-typed `pages_read` on a chapter-measured book is ignored
instead of stored.

**`Progress.Meta.ordering` asks the book which column "furthest along" means**,
through a `Case` that joins to it, rather than naming `pages_read` and being
wrong about every chapter-measured read. The archive lists progress through that
ordering and now gets it right for both. Nulls are placed explicitly last, as
decision #17 requires of every ordering here.

The overview keeps its single subquery: it selects the column this book is
measured in, which is one column either way. Two queries at two members and at
twenty-two, still pinned by `assertNumQueries` — decision #19's count is
unchanged, not merely re-measured.

## 26. The progress log is a second model beside `Progress`, not `Progress` itself

Settled while building the progress trail (#18). The issue was filed with two
options and this is the one it closes on.

**A separate append-only `ProgressEntry`, appended beside `Progress`.**
`Progress` keeps its unique row per member per book and keeps meaning "where
this member is now"; every number ever recorded also lands in `ProgressEntry`,
and a member's trail through a book is the list of them. The alternative —
making `Progress` itself append-only, dropping the unique constraint and
deriving the current value from the latest row — is settled against, and
re-opening it means unseating this decision first.

Why, in the order that decided it:

**It changes no invariant the app already leans on.** Dropping
`one_progress_row_per_member_per_book` would take with it the assumption behind
`Progress.units_read`, `Progress.percent`, `Progress.Meta.ordering`,
`history_detail`'s progress list and the `Progress` rows the admin edits, every
one of which reads a row as *the* answer for that member. All of them keep
working untouched here, because the sentence they encode is still true.

**It leaves the write path #9 built alone.** `/progress/update/` still binds one
form to one row and saves it in place, the GET still writes nothing (decision
#18), and the difference is one appended row in the same transaction. Making
`Progress` an insert would need a new answer to what a second identical
submission means, on the route that already had one.

**It leaves the `/progress/` query pin alone.** The overview annotates every
active member through a single correlated subquery, pinned at
`assertNumQueries(2)` at two members and again at twenty-two (decisions #19 and
#25). The overview never reads the log, so the pin holds by construction. The
other shape would put a latest-row-per-member lookup on a table that grows
without bound, on the one page whose whole point is that it does not grow a
query per row.

**The migration is additive.** A new table plus a data migration that writes one
entry per existing `Progress` row; no column dropped, no constraint loosened, no
existing row rewritten, and `dev_seed.json` and anyone's database survive it
untouched. The other shape is a constraint drop over live data, which is the one
migration shape this project has never had to do.

**What it costs, accepted:** two places hold the same number and they can
disagree. **The rule that keeps them honest is that the newest entry always
matches the current row**, and it is held by writing both in one place —
`Progress.record()`, inside one `transaction.atomic()`. It is not enforced by
the database, and an admin editing a `Progress` row straight in `/admin/`
corrects the current value without leaving a dot on the trail. That is the
honest cost, and #31 is where it gets paid off.

**No `save()` override guards the append** — decision #17 unchanged. Recording
progress is an act with a consequence and the consequence is written where the
act is, the same way finishing a book is two explicit saves in one transaction
rather than a hidden side effect.

Five smaller calls that come with it:

- **An unchanged resubmission appends nothing.** Saving 431 when 431 is already
  recorded moves `updated_on`, because the member did say it again, and adds no
  entry. A trail is a record of movement, and three identical dots from
  somebody double-clicking save are noise in the one place this feature exists
  to make readable. `record()` compares against the newest entry rather than
  against the row's old value, so the comparison and the invariant are the same
  check.
- **The backfill takes each row's own `updated_on`.** It is the only timestamp
  there is, and for a single data point it is the right one — it says when that
  value was recorded. One point draws no line, so nothing is inferred from it
  that it cannot support. `recorded_on` is `auto_now_add`, which overwrites what
  is set on the way in, so the data migration inserts and then puts the original
  timestamps back in one statement.
- **The backfill records the unit the row actually holds**, which is chapters
  where the book is measured in chapters and the row has a chapter count, and
  pages otherwise. A row carrying only pages on a book that has since moved to
  chapters is backfilled in pages, because pages are what somebody typed —
  decision #25's rule applies to the backfill as much as to the write path, and
  the trail then names those entries as recorded in the other unit rather than
  silently reading them against this one.
- **An entry carries one of its two columns and never both or neither**, as a
  `CheckConstraint` with a `violation_error_message` — the house pattern from
  decisions #2, #17 and #24, so a fixture and a shell meet the rule as well as
  the view does. Two columns rather than one reused, for decision #25's reason
  exactly: a number recorded on one scale must never become readable against
  another.
- **The trail is a CSS bar, not an SVG line.** One dated row per entry, reusing
  the `--rule` track and `--accent` fill `progress.html` already renders, with
  the count and the percentage beside it. An SVG line would need a time axis,
  which is the first step towards the analytics product the design system opens
  by ruling out; and reusing the component the club already reads is smaller
  than introducing a second visual language. No JavaScript and no dependency —
  a progress bar is a CSS width.

The route this adds, `/books/<pk>/progress/<member_pk>/`, is public like every
other read in this app, and is in `_docs/api.md`.

## 27. The trail shows one scale, counts the other, and names its changes in text

Settled while building the trail page (#18). Calls the issue's criteria left to
the implementer.

**Only entries recorded in the unit the book is measured in now are on the
trail; the rest are counted out loud.** A book that moved from pages to chapters
shows "N earlier entries were recorded in pages ... not on this trail" rather
than a blank page or a page count read against a chapter total.

Why: decision #25 � a number recorded on one scale is never readable against
another. Hiding them silently would make the page look like the member recorded
nothing, which decision #19 says is a different sentence. The entries stay in
the database untouched.

**The first entry on a trail has no change figure, and a change never crosses
the filter above.** The oldest visible entry is compared with nothing, so a
chapter entry is never "+6 chapters" over a page entry.

**Changes are text, signed, and a decrease keeps its minus** ("-173 pages,
-20%"). No colour or arrow carries the meaning. When the book has no
denominator the page change is still named but no percentage change is invented.

**A trail with one entry says there is nothing to compare it to yet** (one point
draws no line, decision #26). A member with no `Progress` row at all gets "has
not recorded anything", never a bar at zero.

**Four queries whatever the trail's length** � book, member, row, entries with
`progress__book` joined in � pinned by `assertNumQueries`, because
`units_read` and `percent` on each entry would otherwise ask the book per dot.

**The overview links only active members; the archive links every row,** the
deactivated member's included (decision #3).

## 28. Replies are notes with a parent: one level, cascade, oldest first

Settled while building replies (#19). Calls the issue left to the implementer,
plus the ones it fixed, so they are written down once.

**A reply is a `Note` whose nullable `parent` points at a top-level note.** One
model, one removal rule (`may_be_removed_by`), one route (`note_delete`), and
one column. A separate `Reply` model would have meant a second copy of all
three. Replies are notes, so decision #7 applies: they are immutable and
deletable, never editable.

**One level, enforced in `Note.clean()` and `ReplyForm`, not by a
`CheckConstraint`.** The two rules - the parent is not itself a reply, and the
parent is on the same book - compare a row with *another* row. A database
`CheckConstraint` only sees its own row, so it cannot say either. This departs
from the house pattern of decisions #2, #17 and #24 for that reason alone. The
form is the path the app uses: `ReplyForm.parent` is a `ModelChoiceField` over
the current book's top-level notes (decision #21), so a reply's id, a note on a
finished book (decision #23), a missing id and `abc` are all one form error
and nothing is written. A fixture or a shell can still skip `clean()`; that is
the cost of the rule living above the schema. There is no `save()` override
(decision #17).

**Deleting a top-level note deletes its replies (`CASCADE`).** The alternatives
- reparenting, or a "[removed]" tombstone - need either a rule about who
inherits a thread or a second kind of row, and both are larger than the club
needs. The cascade is stated before the POST on the button ("Remove (also
removes N replies)") and after it in the message, because a destructive action
that surprises is worse than one that is merely destructive. `Note.author`
stays `PROTECT` (decision #20).

**Replies read oldest first under their note; top-level notes stay newest
first.** A conversation reads downward. The top-level order is unchanged
(decisions #7 and #20).

**A reply posts to `/notes/`, told apart from a note by the presence of a
`parent` key.** No per-note route. A present-but-empty or junk `parent` is a
reply with a bad target, not a plain note, so it errors rather than quietly
becoming a top-level note. A target error has no note to sit under, so it is
shown above the list; a body error sits under the note replied to, and every
other reply form stays unbound.

**Replies are not notes for counting or listing.** The notes page and the
archive list top-level notes only, with replies prefetched beneath them in one
query, so the page's query count does not grow with the thread (decision #19).

## 29. History search: case-insensitive substring, every word, title or author

Settled while building search on `/history/` (#20).

**A search is `?q=` on the existing page, a GET.** It reads and changes nothing, so
it is public like the rest of `/history/`. There is no separate results route.

**Matching: split `q` on whitespace; every word must appear, ignoring case, as a
substring of the title or of the author.** Words may match in different fields and in
any order, so `ursula dispossessed` finds *The Dispossessed*. It is `icontains`, which
Django escapes, so `%` and `_` match themselves and `?q=%` does not match every book.
No ranking, no fuzziness, no accent folding ("Jose" and "Jose" with an accent stay
different, as with member names in decision #13).

**An empty search is the unfiltered list.** A blank or whitespace-only `q` is no
search: the full archive, no "no match" message, no "Show all books" link.

**The filter reads only the book's own columns,** so it adds no join and the rating
annotations are not inflated. It sits inside the existing queryset after the explicit
`order_by` of decision #17, so results keep that order and the query count stays fixed
(decisions #19 and #23). The current read is excluded as always (decision #22).

**`q` is trimmed and cut at 200 characters** (the length of a title or author) so an
over-long value is a normal search, not a 500. The echoed query is autoescaped.

**The two empty states differ.** "The club has not finished a book yet" shows only
when the archive itself is empty and no search was made; a search with no results
names the query and links back to the full list.

## 30. Reopen keeps the rating and scores, clears only `finished_on`, and refuses while another book is current

**Reopening is the inverse of finishing, and only moves the flag.** `book_reopen` sets
`is_current=True` and clears `finished_on`. `started_on`, the club `rating`, every
member score and every progress row, note, reply, question and answer stay on the row
(decision #2): scores sit dormant while the book is current (decision #23) and apply
again when it is finished a second time. The finish form already defaults its date to
today, so re-finishing needs no special case.

**Refused while another book is current.** The partial unique index allows one current
read (decision #2). The admin finishes the current book first; the app never swaps or
finishes it automatically. The confirmation page says so, a POST adds an error message
and changes nothing, and an `IntegrityError` from a race is caught the same way, so
there is no 500.

**Admin-only, re-checked in the view; a current or unknown book is a 404.** A GET only
renders the confirmation page; the change is a POST with CSRF and a redirect home
(decisions #14 and #16). The "Reopen" link on the archive page is cosmetic.

## 31. "Since you last looked" is in-site only, with a per-member marker and a null baseline

Settled while building the home page panel (#22).

**In-site only.** The panel is the whole feature. Email needs a mail backend, stored
addresses and an unsubscribe story, so it is #41; notes and replies in the panel are #40.

**One marker per member: `Member.notifications_seen_at`.** A nullable datetime. There is
no per-item read state, no badge and no history; the marker moves forward for everything
at once. It is a convenience, not a boundary (decisions #4 and #5): anyone may pick
anyone, so anyone may clear anyone's panel.

**Null means "since the start of `joined_on`".** A member who has never pressed the button
sees everything on the current book created after midnight (local time) of the day they
joined. Existing members therefore see the current book's discussion once, until they
mark it seen.

**What counts, all on the current book only:** each question created after the marker; a
count of answers by other members created after it; and "A new book started" when
`Book.created_on` is after it. A member's own answers never count, and answers are
compared on `created_on`, not `updated_on`, so an edit does not bring one back.
`Book.created_on` is new because the date fields are optional and carry no time; the
migration backfills existing books from `started_on` (midnight) or the migration time.
The dev seed sets it explicitly, since a raw fixture load skips `auto_now_add`.

**GETs never stamp.** Only `POST /seen/` writes the marker, then redirects home (decision
#16). GET is 405. With nobody identified the POST changes nothing and still redirects
rather than 403, because the caller wanted the panel gone and there is nothing to stamp.
An empty panel is not rendered at all; a deactivated member is unidentified (decision #3)
and sees none.

## 32. CI runs the same two commands as the local workflow, on Django's runner

`.github/workflows/ci.yml` runs `uv sync --locked`, `manage.py check` and
`manage.py test` on push to `master` and on every pull request, with the Python
version read from `.python-version`. These are the commands in AGENTS.md, with
nothing added: no `migrate`, `loaddata` or `runserver`, no secrets, no
`db.sqlite3` (the runner builds a temporary test database). `--locked` makes a
stale `uv.lock` fail the job instead of being quietly rewritten.

Decision #12's "no CI yet" reason no longer holds, but its other reasons do: the
suite's assertions are `TestCase` methods, `parametrize` is not needed, and
pytest would still cost two dependencies and a second idiom. So pytest is still
not added, and neither is any test-reporting dependency. Revisit only if
reporting is actually wanted, as #12 already says.

Out of scope here and unchanged: deployment hardening (#42), coverage, linting,
matrix builds and branch protection.

## 33. Admin mode expires on idle and on total age, and the PIN rotates the session key

Settled while building #24. Decision #5 still holds: this is hygiene, so a forgotten
admin tab does not stay open for the two-week session cookie. It is not security, and
the PIN is still not a permission boundary.

**Two plain settings, not environment variables.** `CLUB_ADMIN_IDLE_SECONDS` (default
1800) and `CLUB_ADMIN_MAX_SECONDS` (default 28800), in `reading_club/settings.py`.

**Three session keys.** `is_club_admin` (the flag, unchanged), `club_admin_started_at`
and `club_admin_last_used_at` (epoch seconds from `timezone.now()`), set together by a
correct PIN. One helper, `club.identity.is_admin(request)`, is the only code that reads
the raw flag: `club_admin_required`, the `is_club_admin` context processor and the two
views that used to read it all call it. It returns False and removes all three keys when
idle time or total time exceeds its limit, and otherwise moves `club_admin_last_used_at`
forward, so even a GET that only shows admin links keeps the window open.

**A flag without timestamps is expired.** A session written before this change, or by
a test, does not stay admin forever; the next check clears it. Tests set admin mode with
`enter_admin(session)` from `club/tests/helpers.py`, which writes all three keys.

**Expiry is silent and touches only admin mode.** The refusals are the existing ones
(decision #14): a GET redirects to `/admin-pin/?next=...`, a POST is a 403. No message is
added. `member_id` is never touched, so the viewer is still identified. `POST
/admin-pin/exit/` removes the flag and both timestamps.

**A correct PIN calls `session.cycle_key()`** before the flag is set; a wrong PIN does
not. `member_id` survives the rotation.

Still out: rate limiting after wrong PINs (#45), changing the PIN from the UI (#46), and
any expiry warning or countdown.

## 34. Audiobooks are measured in whole minutes, typed as "4h 12m"

Settled while building #25. An audiobook's chapter breaks do not match the print
edition, and a page count means nothing to someone listening. Time is its own
measure.

**Minutes are the stored unit.** `Book.total_minutes`, `Progress.minutes_read` and
`ProgressEntry.minutes_read` are nullable `PositiveIntegerField`s, one column per
unit as decision #25 settled. Minutes are never written into `pages_read` or
`chapters_read`, and the migration is additive and rewrites no existing row. No
`DurationField`, no seconds, no decimal hours, no third-party parser.

**`Book.measure` gains a third answer.** `"minutes"` when `total_minutes` is set and
positive, then `"chapters"`, then `"pages"`. A `total_minutes` of 0 reads as no
duration, as decision #24 says of chapters, and the form refuses it outright. The
`Book` check constraint now allows at most one of the three totals. The
`ProgressEntry` constraint requires exactly one of its three columns. `Book.unit_column`
names the `Progress` column a book is counted in, so no caller branches on the
measure itself.

**Accepted input**, case-insensitive with surrounding spaces ignored: `4h 12m`,
`4h`, `12m`, `90m`, `4:12`, and a bare `0` for a recorded zero. Refused with a
field error that shows an example: empty or non-time text, decimals such as `4.5h`,
negatives, `0` as a book total, and minutes of 60 or more when hours are also given
(`1h 75m`; `75m` alone is fine). The parser is a small regex function in
`club/duration.py`, and `MinutesField` wraps it for the book form, the progress form
and the admin forms, so all three take the same format and redisplay stored minutes
as time.

**One formatter.** `format_minutes` gives `4h 12m`, `3h`, `45m`, `0m`. The raw
count is never shown to a member: not in the overview, the trail, the archive, the
admin, the "You are ... in" sentence or a form error. Templates reach it through the
`club_units` filters (`counted`, `counted_of_total`, `signed`), which call
`Book.describe_units` and `Book.describe_change`.

**The "other measure" sentence on the trail counts every other unit** (decision #27).
It used to say pages or chapters. It now names each unit that the skipped entries
were recorded in, joined with "and", and the unit the book is measured in now,
where minutes read as "listening time": "recorded in pages, before this book was
measured in listening time". The trail still lists one scale only.

**A pages-only or chapters-only row on a minutes book reads as not started**
(decision #19), and the overview stays at two queries.

**`Progress` is registered in `/admin/`** so a row can be corrected in time. As with
any direct admin edit, that moves the current value without a dot on the trail
(decision #26).

Out: ebook locations as a fourth measure, left to #47; converting a row between
measures, left to #29 and #30; seconds, playback speed and per-chapter timestamps.
