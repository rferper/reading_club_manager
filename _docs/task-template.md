# Task template

The shape a new issue takes. The existing backlog in `_docs/tasks.md` uses a
shorter Goal-plus-Description form; anything added from here on gets this fuller
one, because a task written after the plan has no scope document to lean on.

---

## Goal

One or two sentences on what should be true when this is done.

## Acceptance criteria

- [ ] A statement you can check by looking at the result
- [ ] One line per case, including the awkward ones — the empty state, the
      second submission, the member who is not identified
- [ ] At least one that names a test: what must fail before, and pass after

## Out of scope

- Something a reader might reasonably assume is included, and is not
- Where it went instead, if it went somewhere (#12)

## Constraints

- Files this should stay inside
- Libraries it may not add, patterns it must follow
- Decisions in `_docs/decisions.md` it must respect

## Context

Enough for someone who has read no other issue: which models exist, which
conventions apply, which document to read first.

---

## Writing them

- **Title is imperative and specific.** "Add session-based viewer identity", not
  "Identity work".
- **One sitting.** If it cannot be finished and closed in one go, it is two
  issues.
- **Standalone.** Assume the reader has read no other issue. Repeat the context
  they need rather than pointing at issue #6.
- **Acceptance criteria are observable.** "Progress is tracked correctly" is not
  checkable. "Submitting progress twice keeps only the second value" is.
- **Name the awkward cases in the criteria**, because those are the ones that get
  skipped: the empty state, the duplicate submission, the deactivated member, the
  POST that arrives without the session flag it needed.
