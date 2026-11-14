from django.conf import settings
from django.utils import translation


class DefaultEnglishMiddleware:
    """Keep English until the visitor explicitly chooses a language."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if settings.LANGUAGE_COOKIE_NAME not in request.COOKIES:
            translation.activate("en")
            request.LANGUAGE_CODE = "en"
        return self.get_response(request)
