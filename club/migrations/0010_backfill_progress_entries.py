"""One entry per existing `Progress` row, so no trail starts empty.

Additive, like every migration this feature ships (decision #26): a row that
already existed keeps its value, its timestamp and its place, and gains a
first dot on its trail carrying the number it already had. Nothing is
rewritten, no `Progress` row is touched, and running it against an empty
database does nothing at all.
"""

from django.db import migrations


def backfill_entries(apps, schema_editor):
    """Give every `Progress` row the entry it would have had all along.

    The unit is the one that row actually holds: the chapter count where the
    book is measured in chapters and the row has one, and the page count
    otherwise. A row carrying only pages on a book that has since moved to
    chapters is backfilled in pages, because pages are what somebody typed —
    decision #25's rule, that a number recorded on one scale is never readable
    against another, applies to the backfill as much as to the write path.

    `updated_on` is the timestamp, because it is the only one there is and for
    a single data point it is the honest one: it says when that value was
    recorded. One point draws no line, so nothing is inferred from it that it
    cannot support.
    """
    Progress = apps.get_model("club", "Progress")
    ProgressEntry = apps.get_model("club", "ProgressEntry")
    db_alias = schema_editor.connection.alias

    rows = (
        Progress.objects.using(db_alias)
        .select_related("book")
        .filter(entries__isnull=True)
        .order_by("pk")
    )

    entries = []
    timestamps = []

    for progress in rows:
        in_chapters = (
            bool(progress.book.total_chapters) and progress.chapters_read is not None
        )
        entries.append(
            ProgressEntry(
                progress=progress,
                pages_read=None if in_chapters else progress.pages_read,
                chapters_read=progress.chapters_read if in_chapters else None,
            )
        )
        timestamps.append(progress.updated_on)

    if not entries:
        return

    # `recorded_on` is `auto_now_add`, which overwrites whatever is set on the
    # way in — so the insert is followed by one statement putting the original
    # timestamps back. A backfilled entry dated today would claim the club read
    # the whole book this afternoon.
    created = ProgressEntry.objects.using(db_alias).bulk_create(entries)

    for entry, recorded_on in zip(created, timestamps):
        entry.recorded_on = recorded_on

    ProgressEntry.objects.using(db_alias).bulk_update(created, ["recorded_on"])


def drop_entries(apps, schema_editor):
    """Empty the log again, so the migration is reversible.

    Nothing else holds an entry, and `0009` drops the table straight after
    this, so there is nothing to preserve on the way back down.
    """
    ProgressEntry = apps.get_model("club", "ProgressEntry")
    ProgressEntry.objects.using(schema_editor.connection.alias).all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("club", "0009_progressentry"),
    ]

    operations = [
        migrations.RunPython(backfill_entries, drop_entries),
    ]
