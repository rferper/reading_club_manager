# Reading Club Manager — Build Backlog

Tasks for building the v1 scope described in `_docs/plan.md` as a Django app.
Each task is sized for a single session and written to be picked up without
having read the others.

Shared context for every task: this is a uv-managed Django project. The Django
project package is `reading_club/`, the single app is `club/`, and `manage.py`
sits at the repository root. Run commands with `uv run python manage.py ...`.
Storage is SQLite. There is no login system — members are rows in a `Member`
model, not Django `User` objects.

Two conventions cut across the whole app. First, a viewer identifies themselves
once per session by picking their name from the roster; the chosen member is
held in the session and exposed to every template as `current_member`, so no
individual form ever asks the viewer to re-pick their name. Second, admin-only
actions are gated by a shared PIN held in the session, not by Django's
`/admin/` superuser login.

## 1. Set up the project skeleton with a passing test
Goal: A clean Django project that runs and has one test proving the setup works.
Description: Confirm the `reading_club` project and `club` app are wired together, run the initial migrations to create `db.sqlite3`, and add a minimal smoke test in `club/tests.py` that requests the site root and asserts a 200 response. Add a placeholder home view and URL route so that test has something to hit, and set `TIME_ZONE` in settings to the club's actual zone so timestamps do not display in UTC. Done when `uv run python manage.py test` passes and `uv run python manage.py runserver` serves a page.

## 2. Create the base template and site navigation
Goal: A shared page layout every other screen extends.
Description: Add a `club/templates/club/base.html` with a header, a navigation bar linking to Home, Members, Progress, Discussion, and History, and a content block for child templates. Include simple CSS in a static file so pages are readable without a frontend framework, and leave a clearly marked slot in the header where the "you are …" and "admin mode" indicators will later sit. Done when a stub page extends the base template and renders with working navigation links.

## 3. Add the Member model
Goal: Store the club roster in the database.
Description: Create a `Member` model in `club/models.py` with a unique name, a role field, and an `is_active` flag, then register it in `club/admin.py` and generate and run its migration. Members are added by an admin only, so no self-registration flow is needed; the `is_active` flag exists because members are deactivated rather than deleted, so that anything they wrote keeps its attribution. Done when members can be created, listed, and deactivated through the Django admin.

## 4. Add PIN-based admin gating
Goal: Protect admin-only actions behind a shared PIN instead of a login system.
Description: Store an admin PIN in `reading_club/settings.py`, and build a small form view that compares the submitted value using `hmac.compare_digest` and records a flag in the session when it matches. Add a reusable decorator that other views use to require that flag, a way to clear it, and a template context entry so templates can hide admin controls — but never render the PIN itself back into the HTML, and always re-check the flag in the view rather than trusting a hidden button. Done when a gated URL redirects to the PIN form without the flag, the correct PIN grants access for the rest of the session, and a gated POST is still rejected when the button is hidden.

## 5. Build the member roster page
Goal: Let an admin add, edit, and deactivate club members from the site.
Description: Build a page listing all `Member` rows with their roles and active state, plus forms to add a member, rename one, and toggle whether they are active, using Django `ModelForm`s. Reading the roster is open to everyone; the add, edit, and deactivate controls are admin-only actions behind the PIN gate, and duplicate names should produce a form error rather than a server error. Done when an admin can add and deactivate a member through the browser and a non-admin sees the list but no edit controls.

## 6. Add session-based viewer identity
Goal: Let a viewer say who they are once, and have the whole site remember.
Description: Build a small page where a viewer picks their name from a dropdown of active members, store the chosen member's id in the session, and add a context processor exposing `current_member` to every template so the header can show "You are: Ada — switch" or an invitation to identify. Add a decorator that redirects unidentified visitors to the picker and returns them where they came from afterwards, and make the context processor clear the session key gracefully if that member is later deactivated or removed. Done when picking a name persists across pages, switching works, and a stale session id does not raise an error.

## 7. Add the Book model with a current-book designation
Goal: Represent both the book being read now and every book read before.
Description: Create a `Book` model in `club/models.py` with title, author, total pages, a start date, an optional finish date, an optional rating, and a field marking it as the club's current read. Enforce that at most one book is marked current, treat "no current book" as a legitimate state the club can sit in between reads, and register the model in `club/admin.py`. Done when books can be created through the admin and a second book cannot be marked current while one already is.

## 8. Build the current book page
Goal: Give the club a home screen showing what they are reading now.
Description: Build a view and template that display the current `Book`'s title, author, and start date, with a clear empty state when no book is marked current. This page becomes the landing page and the hub that links out to progress, discussion, and history. Done when the site root shows the current book, or a "no book selected" message when there is none.

## 9. Add the progress model and update form
Goal: Let each member record how far they have read.
Description: Create a `Progress` model linking a member to a book with a pages-read number, deriving the percentage from the book's total pages rather than storing it. Build a form that records progress for whoever the session says the viewer is, updating their existing row for that book instead of creating duplicates, and bounce unidentified visitors to the identity picker first. Done when a member can submit progress twice and only their latest value is kept, and when submitting while no book is current is refused cleanly.

## 10. Build the group progress overview
Goal: Show at a glance who is ahead and who is behind.
Description: Build a page listing every active member alongside their progress on the current book, sorted furthest-along first, showing both pages read and the derived percentage as a simple CSS bar. Members with no recorded progress appear with zero rather than being omitted, and deactivated members are left out entirely. Done when the page reflects submitted progress and orders members correctly.

## 11. Add free-text notes on the current book
Goal: Let members post spontaneous thoughts about the book.
Description: Create a `Note` model with an author, the book it belongs to, body text, and a creation timestamp, then build a page listing notes newest-first with a form to add one, attributed to the session's current member. Any identified member can post without the admin PIN; deleting a note is restricted to its author or an admin and must be a POST, and note bodies render as escaped text with line breaks preserved. Done when a member can add a note and see it appear attributed to them, and a deactivated member's old notes still show their name.

## 12. Add admin-posted discussion questions
Goal: Let the admin seed structured discussion prompts.
Description: Create a `Question` model with question text, the book it belongs to, an ordering field, and a timestamp, and build admin-only forms behind the PIN gate for adding, reordering, and deleting questions. Build a page listing the current book's questions in order for everyone to read, and warn on the delete confirmation that removing a question also removes its answers. Done when an admin can post a question, all visitors can see it listed, and a non-admin POST to the create URL is rejected.

## 13. Add member responses to discussion questions
Goal: Let members answer each posted discussion question.
Description: Create an `Answer` model linking a member and a question with body text and timestamps, unique per member per question so that resubmitting updates the existing answer in place rather than piling up duplicates or raising an integrity error. Extend the questions page so each question shows everyone's answers, with a form for a member who has not answered and an edit affordance for one who has. Done when two different members can answer the same question, both answers show under it, and one member editing their answer changes it rather than adding a second.

## 14. Build the reading history archive
Goal: Give the club a permanent record of every book it has read.
Description: Build a page listing all books that are not the current read, newest-finished first, showing title, author, the dates read, and the rating if one was given, with a detail page replaying that book's notes and answers read-only. Include admin-only controls behind the PIN gate for editing a history entry and for finishing the current book, which records the finish date and rating and clears the current-read flag while leaving all its progress, notes, and answers intact. Done when finishing the current book moves it into the history list and the archive shows every past book with no cap.

## 15. Add a seed fixture and write the README
Goal: Get a fresh clone from checkout to a browsable demo in one command.
Description: Ship a `dev_seed.json` fixture with a few members, one current book with progress on it, a couple of discussion questions with answers, and one finished book in the archive. Write the README to cover `uv sync`, `migrate`, `loaddata`, and `runserver`, where the admin PIN is configured, and an explicit note that the PIN is a convenience and not real security. Done when loading the fixture into a fresh database produces a fully populated app and a newcomer can follow the README without asking questions.
