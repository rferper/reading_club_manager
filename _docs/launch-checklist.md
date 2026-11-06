# Launch checklist

What to do before the club's friends use the app on a real URL. The app itself is
finished (v1 and v2 built, 946 tests passing, `manage.py check` clean, no known
dependency vulnerabilities). What is left is choosing a host and switching the
settings out of development mode.

Last reviewed: 2026-11-06.

## 1. Decide where it runs (issue #42)

Still open, to be decided by the owner. Options discussed:

| Option | Cost | Data | Catch |
| --- | --- | --- | --- |
| PythonAnywhere free account | Free, no card | SQLite on a persistent disk | URL like `name.pythonanywhere.com`; click "extend" every few months; free limits can change, check them first |
| Own PC + Cloudflare Tunnel | Free | Stays on your PC | Only online while the PC is on |
| Local only | Free | Your PC | Friends cannot reach it unless on your network |

Avoid free hosts with a temporary disk: SQLite would be wiped on restart and the
club's history lost.

Record the choice on #42 and in `_docs/decisions.md`. AGENTS.md: do not add a
dependency (WhiteNoise, gunicorn) without asking; PythonAnywhere needs neither.

## 2. Harden the settings (one build issue, filed after step 1)

Today `reading_club/settings.py` is in development mode. Before going live:

- [ ] `DEBUG` off, read from an environment variable (a crash must not show code or settings).
- [ ] New `SECRET_KEY`, read from the environment. The current one is committed in git, so treat it as public.
- [ ] `ALLOWED_HOSTS` set to the real hostname (the app will not start with it empty and `DEBUG` off).
- [ ] `STATIC_ROOT` set and static files served (Django stops serving CSS when `DEBUG` is off).
- [ ] Once on HTTPS: `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_SSL_REDIRECT` on.
- [ ] `uv run python manage.py check --deploy` shows no real issues. Ignore `mail.E001`: the app sends no email.

## 3. Configure on the host (not in git)

- [ ] `CLUB_ADMIN_PIN`: set a long PIN, 8 or more digits. The default `0000` is public. Guesses are not rate limited (decision 51), so length is the protection.
- [ ] `SECRET_KEY` and `DEBUG` environment variables from step 2.
- [ ] Never commit `.env` files or `db.sqlite3` (both gitignored).

## 4. First run on the host

- [ ] `uv sync`
- [ ] `uv run python manage.py migrate`
- [ ] `uv run python manage.py collectstatic` (if step 2 adds `STATIC_ROOT`)
- [ ] Do not `loaddata dev_seed` on the real club; it is demo data. Add the real members instead.
- [ ] Add members on the Members page (enter the PIN first), then start the first book.
- [ ] Django `/admin/`: only create a superuser if needed, with a strong password.

## 5. Smoke test with a phone before sharing the link

- [ ] Home page loads with CSS.
- [ ] Pick a name, record progress, post a note, reply, agree.
- [ ] Wrong PIN is refused; right PIN turns admin mode on and off.
- [ ] A bad URL shows a plain 404, not a debug page.

## 6. Keep going

- [ ] Back up `db.sqlite3` now and then (copy the file). It is the whole club history.
- [ ] #39 (flaky test) is open; it did not reproduce in 6 full runs. Note the failing test name if it ever shows.

## Things to know

- Anyone can pick any member's name; the PIN is a convenience, not security (decision 5). Treat the site as friends-only.
- Note and answer text has no length limit beyond Django's roughly 2.5 MB request cap.
- Decisions already settled are in `_docs/decisions.md` (see 51 for the latest batch); do not re-ask them.
