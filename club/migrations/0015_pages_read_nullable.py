"""`Progress.pages_read` becomes nullable, and stray default zeros become NULL.

Until now `pages_read` was the one count column with `default=0`, so every row
made through the chapters or minutes form also carried a page count of zero.
Once a book changed measure to pages, that zero read as a recorded zero
(decision #19) instead of nothing recorded. Decision #39 makes all three
columns follow one rule.

The data step converts only the rows that are provably the default zero: the
page count is 0, the row has a count in another unit, and no entry on its trail
is in pages. A row with a page entry (even a page entry of 0) and a page-only
zero both keep their value, because somebody did say that. Reversing writes 0
back, since the column is NOT NULL on the way down.
"""

from django.db import migrations, models


def null_unrecorded_pages(apps, schema_editor):
    Progress = apps.get_model("club", "Progress")
    db_alias = schema_editor.connection.alias

    (
        Progress.objects.using(db_alias)
        .filter(pages_read=0)
        .exclude(chapters_read__isnull=True, minutes_read__isnull=True)
        .exclude(entries__pages_read__isnull=False)
        .update(pages_read=None)
    )


def restore_zero_pages(apps, schema_editor):
    Progress = apps.get_model("club", "Progress")
    db_alias = schema_editor.connection.alias

    Progress.objects.using(db_alias).filter(pages_read__isnull=True).update(
        pages_read=0
    )


class Migration(migrations.Migration):

    dependencies = [
        ("club", "0014_chapter_anchor"),
    ]

    operations = [
        migrations.AlterField(
            model_name="progress",
            name="pages_read",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.RunPython(null_unrecorded_pages, restore_zero_pages),
    ]
