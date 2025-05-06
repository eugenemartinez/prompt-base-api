from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from django.http import Http404

def custom_exception_handler(exc, context):
    """
    Custom exception handler for DRF.
    - Returns default DRF JSON errors for APIExceptions.
    - Returns a generic JSON 500 error for unhandled exceptions (when DEBUG=False).
    - Returns default Django HTML error page for unhandled exceptions (when DEBUG=True).
    """
    # Call REST framework's default exception handler first,
    # to get the standard error response.
    response = exception_handler(exc, context)
    request = context.get('request')
    view = context.get('view')

    # If the default handler handled it, return that response
    if response is not None:
        # You could add custom logic here for specific handled exceptions if needed
        # e.g., logging specific validation errors differently
        return response

    # If the default handler did NOT handle it (likely an unhandled exception like 500),
    # provide a generic JSON response *only if DEBUG is False*.
    # In DEBUG mode, let Django's default HTML error page show for easier debugging.
    from django.conf import settings
    if not settings.DEBUG:
        # Log the exception details for server admins
        import logging
        logger = logging.getLogger(__name__) # Or use 'django.request'
        logger.exception(f"Unhandled exception in view {view.__class__.__name__}: {exc}")

        # Provide a generic JSON response to the client
        return Response(
            {"detail": "An internal server error occurred. Please try again later."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    # If DEBUG is True, return None to let Django's default 500 error page render
    return None
