from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone


class Member(models.Model):
    """Someone in the club.

    Members are rows here, never Django ``User`` objects, and they are
    deactivated rather than deleted (decision #3) so that their notes and
    answers keep their attribution. ``role`` is a descriptive label and
    confers nothing (decision #10).
    """

    name = models.CharField(max_length=100, unique=True)
    role = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    joined_on = models.DateField(default=timezone.localdate)

    class Meta:
        ordering = [Lower("name")]
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                name="member_name_unique_ci",
                violation_error_message="A member with that name already exists.",
            )
        ]

    def __str__(self):
        return self.name
