from django import forms

from .models import Member


class AdminPinForm(forms.Form):
    """The one field that opens admin mode.

    `PasswordInput` without `render_value`, so a failed attempt never echoes
    the submitted PIN back into the page. Decision #5: this is a speed bump,
    not security, but there is no reason to print the guess in the response.
    """

    pin = forms.CharField(
        label="Admin PIN",
        widget=forms.PasswordInput,
        max_length=64,
    )


class MemberForm(forms.ModelForm):
    """Add a member, or rename one. Admin-only either way.

    No `clean_name` here on purpose. `Member` already carries both
    `unique=True` and the case-insensitive `UniqueConstraint` from decision
    #13, and a `ModelForm` runs both, so a duplicate arrives as a field error
    and a case-only duplicate as a form-level one. Hand-rolling the check would
    duplicate the rule in a second place and let the two drift apart.

    `is_active` is deliberately absent: deactivating is a POST to
    `club:member_toggle`, not a checkbox someone can flip while renaming.
    """

    class Meta:
        model = Member
        fields = ("name", "role", "joined_on")
        labels = {
            "name": "Name",
            "role": "Role",
            "joined_on": "Joined on",
        }
        help_texts = {
            "role": "A label — \"Founder\", \"Host\". It confers nothing.",
            "joined_on": "Defaults to today. Backdate it for a founding member.",
        }
        widgets = {"joined_on": forms.DateInput(attrs={"type": "date"})}
