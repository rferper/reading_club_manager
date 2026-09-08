# Reading Club Manager

A small shared Django app for one book club: what we are reading now, how far
everyone has got, what we said about it, and every book we have finished.

One club, one app, no accounts. Members are rows in a table, not login
credentials — you tell the site who you are by picking your name off the roster,
and that is remembered for the rest of your session.

## Getting it running

You need [uv](https://docs.astral.sh/uv/) and Python 3.12 or newer. Four
commands from a fresh clone:

```sh
uv sync                                     # install dependencies
uv run python manage.py migrate             # create db.sqlite3
uv run python manage.py loaddata dev_seed   # fill it with a demo club
uv run python manage.py runserver           # http://127.0.0.1:8000/
```

The third one is optional but do it the first time. Without it every page is a
correct and completely empty version of itself, which tells you nothing about
whether the thing works.

`db.sqlite3` is local, disposable and gitignored. Delete it and run the first
three commands again whenever you want a clean club.

## What the seed data contains

`club/fixtures/dev_seed.json` is a club mid-way through *Middlemarch*, having
finished *Piranesi* in June. It is deliberately untidy, because the states worth
looking at are the awkward ones:

- **Five members, one of them deactivated.** Zoe left the club. Her notes and
  answers on *Piranesi* still carry her name, because that is the whole reason
  members are deactivated rather than deleted.
- **A member with nothing recorded.** Dev is on the roster and appears on the
  progress table as "not started", rather than being quietly left out of it.
- **A member who recorded a zero.** Cleo has opened the book. That is a
  different sentence from Dev's and the page says so.
- **A finished book that kept its whole discussion.** *Piranesi* is in the
  history with its progress, notes, questions and answers intact — nothing moved
  anywhere when the club finished it.

## The admin PIN

Admin-only actions — adding members, posting discussion questions, starting and
finishing books — are behind a shared PIN held in your session.

The development default is `0000`. Override it with an environment variable:

```sh
CLUB_ADMIN_PIN=4821 uv run python manage.py runserver
```

Setting it to an empty string makes admin mode unreachable rather than open to
everyone.

**The PIN is a convenience, not security.** It stops a member wandering into the
history editor by accident. It stops nothing else:

- Anyone who can open the site can pick anyone's name and post as them. There is
  no password on identity and there is not going to be one.
- Anyone who learns the PIN is an admin for as long as their session lasts, and
  there is no way to revoke that short of changing the PIN.
- The whole app runs with `DEBUG = True` and Django's development server.

So: **never put anything in this app that would be damaging to leak**, and do
not put it on the open internet as it stands. `_docs/decisions.md` #5 is the
long version of this paragraph, and it is the reason the PIN was never hardened
— hardening it would invite somebody to trust it.

## Running the tests

```sh
uv run python manage.py test                      # the whole suite
uv run python manage.py test club.tests.test_books  # one module
uv run python manage.py check                     # must stay at zero issues
```

Tests live in `club/tests/`, one module per area, and run under Django's own
runner — not pytest, which is a settled decision rather than an omission. Each
run builds and destroys its own database, so the suite never touches
`db.sqlite3`. See `_docs/testing-guidelines.md`.

## Django's own admin

There is a second, entirely separate admin at `/admin/`, which is Django's and
does use real accounts:

```sh
uv run python manage.py createsuperuser
```

It is useful for the handful of things the app deliberately does not do —
un-finishing a book, deleting one — and for looking at the raw rows. Logging out
of it clears your club admin mode too, because they share a session cookie.

## Where everything is

| Path | What it is |
| --- | --- |
| `club/` | the single app: models, views, forms, templates, tests |
| `reading_club/` | project package: settings, root URLconf |
| `_docs/` | the scope, the backlog, the conventions, and the decisions |

Start with [`_docs/plan.md`](_docs/plan.md) for what this is meant to be, then
[`_docs/decisions.md`](_docs/decisions.md) for the calls already settled and why.
[`_docs/api.md`](_docs/api.md) is the map of every URL, who can reach it, and
what it does.
