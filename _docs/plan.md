# Reading Club Manager — v1 Scope

## Purpose
An all-in-one shared tool for managing a reading club: current book progress, discussion, member roster, and full reading history.

## Users
- **Shared/collaborative** — all club members access the same tool and data (not a personal single-user tracker).

## Access Control
- No real login system. Instead:
  - **Admin PIN**: required for admin-only actions (adding/editing members, editing history).
  - **Members**: can freely add their own progress updates, notes, and Q&A responses without a PIN.

## Core Features

### 1. Member List & Roles
- Admin adds/edits members (name + role).
- Members do not self-register.

### 2. Current Book & Progress Tracker
- Book title and author.
- Per-member progress tracked as **percent complete or pages/chapters read** (not just a status label).
- Visibility into who's ahead/behind in the group.

### 3. Discussion (Notes + Q&A)
- **Free-text notes**: any member can add spontaneous thoughts/notes on the current book.
- **Structured Q&A**: admin posts discussion questions; members respond to each.

### 4. Reading History
- **Full, unlimited archive** of past books read by the club.
- Each entry: title, author, dates read (and optionally retained notes/rating).

## Technical Form
- **Single-page web artifact** (HTML), shared among all club members.
- **Shared persistent storage** so data (members, progress, notes, history) is visible to everyone using the tool.

## Out of Scope (for v1)
- Book voting/nomination system for picking the next read.
- Meeting scheduling (dates, locations/links).
- Member self-registration.
- Real authentication/login system (using PIN-based admin gating instead).

---
*Scoped via brainstorming session — ready for build.*
