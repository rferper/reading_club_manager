# URL surface

This project has no REST API. Its interface is a set of server-rendered Django
URLs, and this document is the map of them — the closest thing to a contract the
app has.

All routes live in `club/urls.py` under `app_name = 'club'` and are reversed as
`{% url 'club:name' %}`. The project URLconf mounts them at `/`, alongside
Django's own `/admin/`.

This is the agreed target surface across issues #1–#15, and almost none of it is
built yet. Update a row in the same commit that implements it and move its
status to Built; add a row before inventing a route that is not here.

## Access levels

| Level | Meaning |
| --- | --- |
| Public | Anyone with the link. No session state required. |
| Member | Requires an identified member in the session (#6). |
| Admin | Requires the PIN flag in the session (#4), re-checked inside the view. |

## Routes

| Path | Name | Methods | Access | Purpose | Issue | Status |
| --- | --- | --- | --- | --- | --- | --- |
| `/` | `home` | GET | Public | Current book, author, dates; links out to everything else | #1, #8 | Placeholder page built in #1; #8 fills it in |
| `/who-are-you/` | `identify` | GET, POST | Public | Pick your name; stores it in the session | #6 | Planned |
| `/who-are-you/forget/` | `forget_me` | POST | Public | Clear the session identity | #6 | Planned |
| `/admin-pin/` | `admin_pin` | GET, POST | Public | Enter the PIN; sets the admin session flag | #4 | Planned |
| `/admin-pin/exit/` | `admin_exit` | POST | Admin | Leave admin mode | #4 | Planned |
| `/members/` | `member_list` | GET | Public | The roster, with roles and active state | #5 | Planned |
| `/members/add/` | `member_add` | GET, POST | Admin | Add a member | #5 | Planned |
| `/members/<pk>/edit/` | `member_edit` | GET, POST | Admin | Rename a member or change their role | #5 | Planned |
| `/members/<pk>/toggle/` | `member_toggle` | POST | Admin | Deactivate or reactivate a member | #5 | Planned |
| `/progress/` | `progress` | GET | Public | Everyone's progress on the current book, furthest first | #10 | Planned |
| `/progress/update/` | `progress_update` | POST | Member | Record your own pages read | #9 | Planned |
| `/notes/` | `notes` | GET, POST | GET Public, POST Member | Notes newest-first, plus the add form | #11 | Planned |
| `/notes/<pk>/delete/` | `note_delete` | POST | Author or Admin | Remove a note | #11 | Planned |
| `/questions/` | `questions` | GET, POST | GET Public, POST Member | Questions in order with their answers; POST submits your answer | #12, #13 | Planned |
| `/questions/add/` | `question_add` | GET, POST | Admin | Post a discussion question | #12 | Planned |
| `/questions/<pk>/edit/` | `question_edit` | GET, POST | Admin | Edit or reorder a question | #12 | Planned |
| `/questions/<pk>/delete/` | `question_delete` | GET, POST | Admin | Remove a question and its answers | #12 | Planned |
| `/history/` | `history` | GET | Public | Every finished book, newest first, uncapped | #14 | Planned |
| `/history/<pk>/` | `history_detail` | GET | Public | One past book, its notes and answers, read-only | #14 | Planned |
| `/books/start/` | `book_start` | GET, POST | Admin | Start a new current book | #14 | Planned |
| `/books/<pk>/edit/` | `book_edit` | GET, POST | Admin | Edit a book's metadata | #14 | Planned |
| `/books/<pk>/finish/` | `book_finish` | GET, POST | Admin | Record finish date and rating; clear the current flag | #14 | Planned |

## Conventions

- **POST then redirect, always.** Every successful POST ends in a redirect so a
  refresh cannot resubmit. Say what happened with a Django message.
- **A GET never changes anything.** Delete and finish routes accept GET only to
  render a confirmation form; the change happens on POST with CSRF.
- **Refusals.** A missing member identity redirects to `/who-are-you/` with a
  `?next=` back to where they were. A missing admin flag redirects to
  `/admin-pin/` the same way. A member trying to act on someone else's content
  gets a 403, not a redirect — it is a real refusal, not a missing step.
- **Finished books are read-only** to members. Posting a note or an answer
  against a book that is no longer current is refused even though the URL exists.
