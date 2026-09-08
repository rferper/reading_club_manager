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

## 12. Django's test runner, not pytest — open to revisit

Tests run with `manage.py test`. `pytest` is not installed.

Why: it is what ships with Django, it needs no dependencies, and it handles the
test database without configuration. `pytest` plus `pytest-django` would be
better ergonomics — fixtures, parametrisation, better failure output — at the
cost of two dependencies and a settings shim.

This is the one decision here recorded as genuinely open. It is cheap to change
while the suite is small and gets more expensive with every test written. If it
is going to change, change it early.
