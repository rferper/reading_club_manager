# URL surface

This project has no REST API. Its interface is a set of server-rendered Django
URLs, and this document is the map of them — the closest thing to a contract the
app has.

All routes live in `club/urls.py` under `app_name = 'club'` and are reversed as
`{% url 'club:name' %}`. The project URLconf mounts them at `/`, alongside
Django's own `/admin/`.

This is the whole surface across issues #1-#16, and every row of it is built.
Update a row in the same commit that changes it; add a row before inventing a
route that is not here.

## Access levels

| Level | Meaning |
| --- | --- |
| Public | Anyone with the link. No session state required. |
| Member | Requires an identified member in the session (#6). |
| Admin | Requires the PIN flag in the session (#4), re-checked inside the view. |

## Routes

| Path | Name | Methods | Access | Purpose | Issue | Status |
| --- | --- | --- | --- | --- | --- | --- |
| `/` | `home` | GET | Public | Current book, author, dates; links out to everything else; for an identified member, a "Since you last looked" panel of new questions, other members' new answers and a newly started book (decision #31), and other members' new notes and note replies as counts linking to the notes page (decision #46), and other members' new answer replies as a count linking to the questions page (decision #48) | #1, #8, #40, #60 | Built |
| `/who-are-you/` | `identify` | GET, POST | Public | Pick your name; stores it in the session | #6 | Built |
| `/who-are-you/forget/` | `forget_me` | POST | Public | Clear the session identity | #6 | Built |
| `/seen/` | `mark_seen` | POST | Public | Stamp the viewer's `notifications_seen_at` with now so the home page's "Since you last looked" panel clears, then redirect to `/`. GET is 405. With nobody identified it changes nothing and still redirects. No other route ever writes the marker | #22 | Built |
| `/admin-pin/` | `admin_pin` | GET, POST | Public | Enter the PIN; sets the admin session flag and rotates the session key. Admin mode expires on idle or max age (decision #33) | #4 | Built |
| `/admin-pin/exit/` | `admin_exit` | POST | Admin | Leave admin mode | #4 | Built |
| `/members/` | `member_list` | GET | Public | The roster, with roles and active state | #5 | Built |
| `/members/add/` | `member_add` | GET, POST | Admin | Add a member | #5 | Built |
| `/members/<pk>/edit/` | `member_edit` | GET, POST | Admin | Rename a member or change their role | #5 | Built |
| `/members/<pk>/toggle/` | `member_toggle` | POST | Admin | Deactivate or reactivate a member | #5 | Built |
| `/progress/` | `progress` | GET | Public | Everyone's progress on the current book, furthest first, each row with a "This week" cell: movement over the last 7 days (`RECENT_DAYS`) in the book's unit, e.g. "+40 pages, +40%", "no change this week", "first entry this week", or a dash when nothing is recorded; two queries at any roster size | #10, #32 | Built |
| `/progress/update/` | `progress_update` | GET, POST | Member | How far you have read the current book, counted in whatever that book is measured in — pages, chapters, or time listened (typed as "4h 12m"): GET the form, POST to save. A save also appends a `ProgressEntry` unless the number is unchanged | #9, #17, #18, #25 | Built |
| `/notes/` | `notes` | GET, POST | GET Public, POST Member | Top-level notes newest-first, each with its replies beneath it oldest-first, plus the add form and a reply form per note. POST with a hidden `parent` is a reply to that top-level note of the current book (author from the session, book from the parent); anything else is a new note. A `parent` that is missing, junk, a reply, or on a finished book is a form error and writes nothing. Form fields: `body`, optional `chapter` (whole number, 1 up to the book's `total_chapters` when it has one; ignored on a reply). Query: `?chapter=N` lists only top-level notes anchored to chapter N, with their replies; a missing, blank or non-integer value is ignored (decision #35) | #11, #19 | Built |
| `/notes/<pk>/react/` | `note_react` | POST | Member | Toggle the viewer's "Agree" on a top-level note of the current book: adds the reaction, or removes it when already there. Always redirects to unfiltered `/notes/`. A reply, a missing note or a note on a finished book writes nothing and redirects with an error message; no identity is a 403, a GET is a 405 | #33 | Built |
| `/notes/<pk>/delete/` | `note_delete` | POST | Author or Admin | Remove a note or a reply. Removing a top-level note also removes its replies and the message says how many | #11, #19 | Built |
| `/questions/` | `questions` | GET, POST | GET Public, POST Member | Questions in order with their answers, each answer with its replies beneath, oldest first; POST submits your answer, or a reply when the body has an `answer` key (present-but-blank or junk is a reply with a bad target and errors, it never becomes an answer). A reply saves with the session member as author and redirects back | #12, #13, #34 | Built |
| `/answers/replies/<pk>/delete/` | `answer_reply_delete` | POST | Author or Admin | Remove one reply to an answer, redirecting to `/questions/`. Another member or no identity is a 403, a GET is a 405, an unknown pk is a 404. A reply on a finished book's answer is refused with a message and kept | #34 | Built |
| `/questions/add/` | `question_add` | GET, POST | Admin | Post a discussion question; optional `chapter` field, same rules as a note's | #12, #26 | Built |
| `/questions/<pk>/edit/` | `question_edit` | GET, POST | Admin | Edit or reorder a question; the optional `chapter` can be set, changed or cleared | #12, #26 | Built |
| `/questions/<pk>/delete/` | `question_delete` | GET, POST | Admin | Remove a question, its answers and their replies; the confirmation page and the success message count the replies when there are any | #12, #34 | Built |
| `/history/` | `history` | GET | Public | Every book that is not the current read, newest finished first, uncapped. Optional `?q=`: case-insensitive substring search of title and author, every whitespace-separated word must match one of them; blank `q` is the full list; `q` is trimmed and cut at 200 characters. Optional `?year=YYYY`: only books whose `finished_on` falls in that calendar year; undated books appear only when no year is chosen; only a year offered in the page's Year select filters, anything else (blank, junk, an unlisted year) is ignored; combines with `q` by AND; the offered years are derived from non-current books with a finish date, newest first, and are not narrowed by `q`. Read-only, no state changes | #14, #20, #36 | Built |
| `/history/<pk>/` | `history_detail` | GET | Public | One book: its progress, notes (with their Agree counts, read-only, shown only when at least 1, and their replies beneath, read-only), answers (with their replies beneath, read-only) and every member's score. The discussion is read-only; an identified member also gets a rating form here, posting to `book_rate`, only when the book has a finish date | #14, #16, #58 | Built |
| `/books/start/` | `book_start` | GET, POST | Admin | Start a new current book | #14 | Built |
| `/books/<pk>/edit/` | `book_edit` | GET, POST | Admin | Edit a book's metadata | #14 | Built |
| `/books/<pk>/finish/` | `book_finish` | GET, POST | Admin | Record finish date and rating; clear the current flag | #14 | Built |
| `/books/<pk>/reopen/` | `book_reopen` | GET, POST | Admin | Make a finished book the current read again. GET renders a confirmation page (and says so when another book is current); POST sets `is_current` and clears `finished_on`, keeping rating, scores and the whole discussion, then redirects to `/` with a message. Refused with a message while another book is current. Current or unknown pk is a 404. Linked from `/history/<pk>/` for admins | #21 | Built |
| `/books/<pk>/delete/` | `book_delete` | GET, POST | Admin | Delete a book and everything attached to it. GET renders a confirmation that counts what goes with it (progress records and entries, notes, replies to notes, reactions, questions, answers, replies to answers, member scores; zero lines omitted) and changes nothing. POST deletes in one transaction and redirects to `/` for the current read, else `/history/`, with a message carrying the totals. Other methods are 405; unknown pk is 404. Linked from `/` and `/history/<pk>/` for admins | #38 | Built |
| `/books/<pk>/rate/` | `book_rate` | GET, POST | Member | Your own score of 1-5 on a finished book: GET the form, POST to save. Posted from the form on `/history/<pk>/`; renders its own page for a direct GET or a rejected score. Refuses the current read ("still reading") and any book with no finish date ("no finish date yet") with a message and a redirect, GET or POST; stored scores on such a book are kept | #16, #27 | Built |
| `/books/<pk>/progress/<member_pk>/` | `progress_trail` | GET | Public | One member's trail through one book: every number they recorded, newest first, dated, in the unit the book is measured in now, with the percentage and the change from the entry before. Unknown book or member is a 404. Linked from `/progress/` and `/history/<pk>/` | #18 | Built |
| `/books/<pk>/progress/<member_pk>/entries/<entry_pk>/delete/` | `progress_entry_delete` | POST | Member (the trail's owner) | Remove one older entry from your own trail on the current book. Deletes only that `ProgressEntry`; `Progress` is untouched. Redirects to the trail with a message. Refused with a message and a redirect when the book is finished or the entry is the newest (save the correct number first, then remove the older one). Unidentified or another member (admin flag does not matter) is a 403; GET is a 405; unknown book, member or entry, or an entry that is not on that member's row for that book, is a 404. Shown as a Remove button on `/books/<pk>/progress/<member_pk>/` | #31 | Built |

## Conventions

- **POST then redirect, always.** Every successful POST ends in a redirect so a
  refresh cannot resubmit. Say what happened with a Django message.
- **A GET never changes anything.** Delete and finish routes accept GET only to
  render a confirmation form; the change happens on POST with CSRF.
- **Refusals depend on the method.** A missing member identity or admin flag on
  a **GET or HEAD** redirects to `/who-are-you/` or `/admin-pin/` with a `?next=`
  back to where they were: the viewer is missing a step, and the redirect is
  that step. On **any other method, POST included**, either missing gate is a
  **403** — a redirect would answer the POST with a GET, silently discard the
  submitted data, and read as success to anything automated; and sending a
  POST-only route through `?next=` would land the viewer back on it as a GET,
  which is a 405. A member trying to act on someone else's content is likewise
  a 403, not a redirect.
- **A submitted `?next=` is validated before it is followed**, with
  `url_has_allowed_host_and_scheme` against this host, falling back to `home`.
  `/admin-pin/` and `/admin-pin/exit/` are rejected as destinations too, so the
  PIN page can never redirect to itself or straight back out.
- **Finished books are read-only for the discussion**, and open for rating.
  Posting a note or an answer against a book that is no longer current is
  refused even though the URL exists. `/books/<pk>/rate/` is the one exception,
  narrowed in decision #23 — you rate a book once you have finished it — and it
  refuses the mirror image, the book the club is still reading, and a book with
  no finish date (decision #36). An unidentified
  POST there is a 403 like everywhere else, and the current-read refusal is a
  redirect with a message rather than a status code: it says the action has
  stopped meaning anything, not that the viewer is the wrong person.
