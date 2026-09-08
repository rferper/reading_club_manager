from django.shortcuts import render


def home(request):
    """Placeholder landing page.

    Issue #8 replaces this with the current book and its details.
    """
    return render(request, "club/home.html")
