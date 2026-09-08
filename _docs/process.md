# Process

## One issue at a time

The backlog in `_docs/tasks.md` is mirrored to GitHub issues #1–#15, where the
issue number is the task number. Pick one, finish it, close it. Do not open a
second until the first is closed or explicitly parked.

## Before starting

- Read the whole issue, including the project context below the rule. Each issue
  is written to be picked up without having read the others.
- Read `_docs/decisions.md`. If the issue appears to contradict something settled
  there, the decision wins — say so on the issue rather than quietly doing it
  your own way.
- Check what already exists. Several early issues describe setup that is partly
  on disk already.

## While working

- Stay inside the task. Anything worth doing that the issue does not cover
  becomes a new issue, not a larger diff.
- Commit regularly, in commits small enough that each one leaves the suite green.
- Put the issue number in the commit message (`#7`) so the history is traceable
  back to the reason.

## Before closing

Walk the "Done when" sentence in the issue clause by clause, then check:

- `uv run python manage.py test` passes
- `uv run python manage.py check` reports zero issues
- Model changes have their migration committed alongside them
- URL changes are reflected in `_docs/api.md` in the same commit
- Any judgment call the issue did not settle is written into `_docs/decisions.md`

The last two matter most. A route that exists only in the code, or a decision
that exists only in someone's head, is how the next task starts by guessing.

## Branches

One branch per issue, named `<number>-<slug>` — `7-book-model`, `4-admin-pin`.
Work merges into `master`.

## When the spec is unclear

`_docs/plan.md` is a scope document, not a specification, and it leaves real
questions open. When you hit one:

1. Check `_docs/decisions.md` — it may already be answered.
2. If not, pick the option that keeps the app simple and says so on the issue.
3. Record it in `_docs/decisions.md` with the reasoning, so the next person
   inherits an answer instead of the same fork.

Do not expand scope to resolve an ambiguity. The plan's "Out of Scope" list is
binding: book voting, meeting scheduling, self-registration, and real
authentication stay out of v1 regardless of how convenient they would be.

## Roles

- PM - grooms a task before anyone implements it, follows _docs/_team/pm.md
- Engineer - implements one groomed task, follows _docs/_team/software-engineer.md
- QA - checks the result against the acceptance criteria, follows _docs/_team/qa-engineer.md
