from django.test import SimpleTestCase


class DeliberateFailure(SimpleTestCase):
    def test_fails_on_purpose(self):
        self.fail("deliberate failure to prove CI goes red (#23)")
