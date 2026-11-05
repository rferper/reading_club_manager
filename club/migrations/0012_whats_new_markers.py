import datetime

from django.db import migrations, models
from django.utils import timezone


def backfill_book_created_on(apps, schema_editor):
    """Give existing books a creation time: their start date, else now.

    Using the start date means the book already being read does not announce
    itself as "new" to members who joined after it began.
    """
    Book = apps.get_model("club", "Book")
    now = timezone.now()
    for book in Book.objects.all():
        if book.started_on:
            book.created_on = timezone.make_aware(
                datetime.datetime.combine(book.started_on, datetime.time.min)
            )
        else:
            book.created_on = now
        book.save(update_fields=["created_on"])


class Migration(migrations.Migration):

    dependencies = [
        ("club", "0011_note_parent"),
    ]

    operations = [
        migrations.AddField(
            model_name="member",
            name="notifications_seen_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="book",
            name="created_on",
            field=models.DateTimeField(auto_now_add=True, default=timezone.now),
            preserve_default=False,
        ),
        migrations.RunPython(backfill_book_created_on, migrations.RunPython.noop),
    ]
