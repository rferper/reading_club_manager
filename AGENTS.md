# AGENTS.md

A small shared Django app for one book club: the current read, each member's
progress, discussion, and the full history of past books. Scope is
`_docs/plan.md` — read it before adding anything that is not in it.

## Commands

- `uv sync` — install dependencies
- `uv run python manage.py runserver` — dev server on http://127.0.0.1:8000/
- `uv run python manage.py test` — the whole suite
- `uv run python manage.py test club.tests.test_books` — one module
- `uv run python manage.py makemigrations club` then `migrate` — after model changes
- `uv run python manage.py check` — must stay at zero issues

There is no `pytest` here and no top-level `tests/` directory. Tests live in
`club/tests/`, one module per area, and run under Django's own runner, which
builds and destroys a temporary database per run. See
`_docs/testing-guidelines.md`.

## Layout

| Path | What it is |
| --- | --- |
| `manage.py` | entrypoint, at the repo root |
| `reading_club/` | project package — settings, root URLconf, wsgi/asgi |
| `club/` | the single app — all models, views, forms, templates |
| `club/tests/` | the suite, one module per area |
| `club/templates/club/` | templates (`APP_DIRS` is on; the project's `DIRS` stays empty) |
| `club/static/club/` | one hand-written stylesheet, no build step |
| `_docs/` | spec, backlog, conventions, decisions |
| `src/reading_club_manager/` | vestigial — **do not delete**, see Rules |

## Rules

- Dependencies are added in `pyproject.toml`. Do not add one without asking.
- Do not delete `src/reading_club_manager/`. It is a leftover stub from the uv
  skeleton, but `pyproject.toml` still declares the `uv_build` backend and a
  `[project.scripts]` entry pointing into it, so removing the directory on its
  own breaks `uv sync`.
- One app. Do not create a second Django app without asking.
- No JavaScript framework, no build step, no REST layer. Django templates,
  `ModelForm`s, and the built-in admin are the whole toolkit.
- **Never trust a hidden button.** Every admin-only action re-checks the session
  flag inside the view. Hiding a control in a template is cosmetic.
- Every internal link goes through `{% url 'club:...' %}`. No hardcoded paths,
  in templates or in tests.
- Anything that changes state is a POST with CSRF, followed by a redirect. No
  GET ever deletes.
- Members are rows in a `Member` model, never Django `User` objects. There is no
  login. `request.user` is not the identity this app runs on — the session's
  `current_member` is.
- Do not commit `db.sqlite3`. It is gitignored, disposable local state.

## Documents

- `_docs/plan.md` — the v1 scope, including what is deliberately out of it
- `_docs/tasks.md` — the backlog, mirrored to GitHub issues #1–#15
- `_docs/process.md` — how work is organized
- `_docs/decisions.md` — calls already settled; read before re-litigating one
- `_docs/api.md` — the URL surface: every route, method, and who may reach it
- Before writing tests, read `_docs/testing-guidelines.md`
- For anything touching the UI, read `_docs/design-system.md`
