# Testing guidelines

## The runner

    uv run python manage.py test

Tests live in `club/tests/`, a package with an `__init__.py` and one module per
area. The runner discovers any file matching `test*.py` under it, so a new area
is a new module and nothing else. What is there now:

| Module | Covers |
| --- | --- |
| `test_pages.py` | the base layout and the landing page |
| `test_members.py` | the `Member` model, its admin, and the roster page |
| `test_admin_pin.py` | the PIN form, the admin gate, what refusal means |
| `test_identity.py` | session identity and the member gate |
| `test_books.py` | the `Book` model and the current-read flag |
| `test_progress.py` | the `Progress` model, its derived percentage, the update form |
| `test_progress_overview.py` | the group table, its ordering, its query count |
| `test_notes.py` | the `Note` model, the notes page, who may remove one |
| `test_questions.py` | the `Question` model, its order, the admin-only controls |
| `test_answers.py` | the `Answer` model, its one-per-member rule, the answer forms |

Put a test in the module that owns the rule it protects, not the module that
owns the URL it happens to hit. Imports inside the package are relative to it:
`from ..models import Book`.

Each run builds a throwaway database and destroys it afterwards, so tests never
touch `db.sqlite3` and never depend on what is in it.

`pytest` is **not** installed, and there is no top-level `tests/` directory.
That is settled, not an omission — see `_docs/decisions.md` #12. Do not add it.
Lean on the `TestCase` assertion helpers instead; they are the reason for the
decision.

## What to test

Every task ships tests for its own "Done when" clauses. Beyond that, spend
effort where the app is actually easy to get wrong:

- **The derived and constrained values.** The progress percentage, including
  `pages_read == total_pages` landing on exactly 100 and a book with no total
  pages recorded. The at-most-one-current-book constraint. One answer per member
  per question, where resubmitting must update rather than raise.
- **The gates, from the outside.** POST to an admin-only URL with no PIN flag in
  the session and assert it is refused. This is the highest-value test in the
  project: hiding a button and enforcing a permission are different things, and
  only this test knows the difference.
- **One smoke test per page**, asserting 200 and one piece of real content. Cheap,
  and it catches the broken-template and misspelled-URL-name class of error the
  moment it appears.
- **The empty states.** No current book, no members, no notes yet. Templates
  raise here more often than anywhere else.

## What not to test

- Django itself. Do not assert that a `CharField` stores a string.
- Exact markup. Assert on content that matters — `assertContains(response, "Ada")`
  — not on the structure of the HTML, which will change.

## How to write them

- Use `django.test.TestCase`; it wraps each test in a transaction and rolls back,
  so tests do not leak into each other.
- Build shared fixtures in `setUpTestData`, not `setUp` — it runs once per class
  rather than once per test.
- Reverse every URL with `reverse('club:...')`. A test with a hardcoded path
  cannot catch a routing change, which is half of what these tests are for.
- To test as an identified member or an admin, write the session directly rather
  than posting through the PIN and identity forms in every test:

      session = self.client.session
      session["member_id"] = self.ada.pk
      session["is_club_admin"] = True
      session.save()

- Name the test after the rule it protects —
  `test_second_current_book_is_rejected` — so a failure report names the broken
  rule instead of a line number.
- One idea per test. A test that asserts five unrelated things fails once and
  hides four.
