# Design system

The club is a handful of people reading a book together. The interface should
feel like a noticeboard — legible, plain, fast — not like an analytics product.

## Constraints

- **One stylesheet**, hand-written, at `club/static/club/style.css`, pulled into
  `base.html` with `{% static %}`. No Tailwind, no Bootstrap, no build step.
- **No JavaScript** unless a task explicitly calls for it. A progress bar is a
  CSS width, not a charting library. Everything works with forms and full page
  loads.
- **Every page extends `club/templates/club/base.html`.** A template that does
  not is a bug.

## Layout

`base.html` owns the site title, the nav, the "you are …" and admin-mode
indicators, the messages block, and a single `{% block content %}`. Child
templates supply content and nothing else.

Content sits in one centred column, `max-width: 46rem`, at every screen width.
The site gets read on a phone during a commute at least as often as on a laptop,
and a single column needs no breakpoints to survive that.

## Tokens

Define these once as custom properties on `:root` and use them everywhere. Do
not introduce a colour that is not in this table without adding it here first.

| Token | Used for |
| --- | --- |
| `--ink` | body text |
| `--ink-muted` | timestamps, roles, secondary labels |
| `--paper` | page background |
| `--panel` | cards, note bodies, table stripes |
| `--rule` | borders and dividers |
| `--accent` | links, progress fill, primary button |
| `--warn` | destructive actions and admin-only affordances |

Two sizes carry the whole site: 1rem body, 1.25rem headings. Add a third only
when a page genuinely needs it.

## Components

- **Panel** — the repeating unit: a note, a question, a history entry. A padded
  box on `--panel` with a `--rule` border. No drop shadows.
- **Progress bar** — a `--rule` track with an `--accent` fill whose width is an
  inline percentage. Always next to the number in text. A bar on its own is
  unreadable to a screen reader and imprecise to everyone else.
- **Byline** — author name and timestamp in `--ink-muted`, placed *under* the
  content it belongs to, never above it.
- **Admin affordance** — anything behind the PIN carries a `--warn` outline, so
  it is visually obvious which controls an ordinary member will never see. This
  is a courtesy to the reader, not a security boundary.
- **Empty state** — a sentence in `--ink-muted` naming what is missing and what
  would fill it: "No book in progress — an admin can start one." Never a blank
  region, and never a bare zero.

## Writing

- Sentence case for headings and buttons: "Add a note", not "Add Note".
- Buttons name the action: "Save progress", "Post note", "Finish this book".
- Speak in the club's own language. "You are: Ada." "Nobody has started this one
  yet." "Ada is 40 pages in."
- Never say "user". They are members.

## Accessibility floor

Non-negotiable, and cheap to hold if done from the first template:

- Every form control has a real `<label>`. A placeholder is not a label.
- Body text meets 4.5:1 contrast against `--paper`. Check `--ink-muted` first —
  it is where this usually fails.
- The page works at 200% zoom with no horizontal scrolling.
- Focus is visible on every interactive element. Do not remove an outline
  without replacing it with something at least as clear.
- Colour never carries meaning on its own, which is why the progress bar always
  has its number beside it.
