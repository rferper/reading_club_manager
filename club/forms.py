from django import forms


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
